"""Cargadores: leen el ORM y arman las entradas de los cálculos puros del negocio."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import F, Q, QuerySet, Sum

from apps.business.models import (
    BusinessGoal,
    DebtStatus,
    OperatingExpense,
    Payable,
    Receivable,
    Sale,
    SaleLine,
)
from apps.core.dates import clamp_day
from apps.core.money import ZERO
from apps.ledger.choices import CategoryGroup, Direction, TxKind
from apps.ledger.models import Transaction
from apps.ledger.services.balances import confirmed, savings_accounts_balance, total_balance
from apps.ledger.services.classification import TRANSFER_KINDS
from apps.workspaces.models import Workspace

from .cash import (
    DEFAULT_HORIZON_DAYS,
    CashItem,
    CashProjection,
    OpenDebt,
    ReserveResult,
    cash_projection,
    commitments,
    expected_inflows,
    operating_reserve,
)
from .indicators import (
    BusinessPeriodInputs,
    ExpensePlan,
    GoalInputs,
    PeriodIndicators,
    SoldLine,
    compute_indicators,
)


def month_bounds(today: datetime.date) -> tuple[datetime.date, datetime.date]:
    """Período de análisis del negocio: el mes calendario."""
    return today.replace(day=1), clamp_day(today.year, today.month, 31)


def _sum(qs: QuerySet[Transaction], **filters: object) -> Decimal:
    total: Decimal = qs.filter(**filters).aggregate(t=Sum("amount", default=ZERO))["t"]
    return total


def _expense_plan(workspace: Workspace) -> list[ExpensePlan]:
    return [
        ExpensePlan(
            ref=str(e.pk),
            name=e.name,
            amount=e.amount,
            frequency=e.frequency,
            due_day=e.due_day,
            is_reducible=e.is_reducible,
        )
        for e in OperatingExpense.objects.for_workspace(workspace).filter(is_active=True)
    ]


def _goal(workspace: Workspace) -> GoalInputs:
    goal = BusinessGoal.objects.filter(workspace=workspace).first()
    if goal is None:
        return GoalInputs()
    return GoalInputs(
        target_sales=goal.target_sales,
        target_margin=goal.target_margin_pct,
        target_profit=goal.target_profit,
        cash_reserve=goal.cash_reserve,
    )


def _open(model: type[Receivable] | type[Payable], workspace: Workspace) -> QuerySet:  # type: ignore[type-arg]
    return model.objects.for_workspace(workspace).exclude(status=DebtStatus.PAGADA)


def _open_total(qs: QuerySet, today: datetime.date) -> tuple[Decimal, Decimal]:  # type: ignore[type-arg]
    balance = F("amount") - F("paid")
    agg = qs.aggregate(
        total=Sum(balance, default=ZERO),
        overdue=Sum(balance, filter=Q(due_date__lt=today), default=ZERO),
    )
    return agg["total"], agg["overdue"]


def load_business_inputs(
    workspace: Workspace, start: datetime.date, end: datetime.date, today: datetime.date
) -> BusinessPeriodInputs:
    lines = [
        SoldLine(
            product_ref=str(line.product_id or ""),
            name=line.description or (line.product.name if line.product else ""),
            qty=line.qty,
            net_amount=line.net_amount,
            unit_cost=line.unit_cost_snapshot,
        )
        for line in SaleLine.objects.filter(
            sale__workspace=workspace, sale__date__range=(start, end)
        ).select_related("product")
    ]
    tax: Decimal = (
        Sale.objects.for_workspace(workspace)
        .filter(date__range=(start, end))
        .aggregate(t=Sum("tax", default=ZERO))["t"]
    )
    period = confirmed(workspace).filter(date__range=(start, end))
    operating_group = Q(category__isnull=True) | Q(category__group=CategoryGroup.GASTO_OPERATIVO)
    variable_group = Q(category__group=CategoryGroup.COSTO_VARIABLE)
    expenses = period.filter(direction=Direction.OUT)
    operating = _sum(expenses.filter(operating_group), kind=TxKind.GASTO) + _sum(
        expenses.filter(category__group=CategoryGroup.GASTO_OPERATIVO), kind=TxKind.PAGO_CXP
    )
    variable_paid = _sum(expenses, kind=TxKind.COMPRA_INVENTARIO) + _sum(
        expenses.filter(variable_group).exclude(kind=TxKind.COMPRA_INVENTARIO),
        kind__in=[TxKind.GASTO, TxKind.PAGO_CXP],
    )
    cash = period.exclude(kind__in=TRANSFER_KINDS)
    receivables, receivables_overdue = _open_total(_open(Receivable, workspace), today)
    payables, payables_overdue = _open_total(_open(Payable, workspace), today)
    return BusinessPeriodInputs(
        start=start,
        end=end,
        currency=workspace.currency,
        lines=lines,
        tax_collected=tax,
        untracked_sales=_sum(period, kind=TxKind.VENTA, direction=Direction.IN, sale__isnull=True),
        other_income=_sum(period, kind=TxKind.INGRESO, direction=Direction.IN),
        operating_expenses=operating,
        uncategorized_expenses=_sum(expenses, kind=TxKind.GASTO, category__isnull=True),
        variable_costs_paid=variable_paid,
        cash_in=_sum(cash, direction=Direction.IN),
        cash_out=_sum(cash, direction=Direction.OUT),
        receivables_open=receivables,
        receivables_overdue=receivables_overdue,
        payables_open=payables,
        payables_overdue=payables_overdue,
        expense_plan=_expense_plan(workspace),
        goal=_goal(workspace),
    )


def _debts(qs: QuerySet) -> list[OpenDebt]:  # type: ignore[type-arg]
    return [OpenDebt(label=d.concept, balance=d.balance, due_date=d.due_date) for d in qs]


def _paid_this_month(workspace: Workspace, today: datetime.date) -> frozenset[str]:
    """Gastos mensuales con categoría cuyo pago del mes ya se registró (monto completo)."""
    start, end = month_bounds(today)
    spent = dict(
        confirmed(workspace)
        .filter(
            date__range=(start, end),
            direction=Direction.OUT,
            kind__in=[TxKind.GASTO, TxKind.PAGO_CXP],
            category__isnull=False,
        )
        .values_list("category_id")
        .annotate(total=Sum("amount"))
    )
    return frozenset(
        str(e.pk)
        for e in OperatingExpense.objects.for_workspace(workspace).filter(
            is_active=True, frequency="mensual", category__isnull=False
        )
        if spent.get(e.category_id, ZERO) >= e.amount
    )


def business_cash_now(workspace: Workspace, today: datetime.date) -> Decimal:
    """Efectivo del negocio hoy, sin las cuentas de ahorro (no es dinero para operar)."""
    return total_balance(workspace, today) - savings_accounts_balance(workspace, today)


@dataclass(frozen=True)
class CashOutlook:
    cash_now: Decimal
    outflows: list[CashItem]
    inflows: list[CashItem]
    projection: CashProjection
    reserve: ReserveResult


def load_cash_outlook(
    workspace: Workspace, today: datetime.date, horizon_days: int = DEFAULT_HORIZON_DAYS
) -> CashOutlook:
    horizon_end = today + datetime.timedelta(days=horizon_days)
    cash_now = business_cash_now(workspace, today)
    outflows = commitments(
        today,
        horizon_end,
        _debts(_open(Payable, workspace)),
        _expense_plan(workspace),
        _paid_this_month(workspace, today),
    )
    inflows = expected_inflows(today, horizon_end, _debts(_open(Receivable, workspace)))
    reserve_goal = _goal(workspace).cash_reserve
    return CashOutlook(
        cash_now=cash_now,
        outflows=outflows,
        inflows=inflows,
        projection=cash_projection(cash_now, today, outflows, inflows, reserve_goal),
        reserve=operating_reserve(cash_now, today, outflows, reserve_goal, horizon_days),
    )


@dataclass(frozen=True)
class BusinessSnapshot:
    indicators: PeriodIndicators
    cash: CashOutlook


def business_snapshot(workspace: Workspace, today: datetime.date) -> BusinessSnapshot:
    """Indicadores del mes en curso y panorama de caja (lo usan el inicio, alertas y el plan)."""
    start, end = month_bounds(today)
    return BusinessSnapshot(
        indicators=compute_indicators(load_business_inputs(workspace, start, end, today)),
        cash=load_cash_outlook(workspace, today),
    )
