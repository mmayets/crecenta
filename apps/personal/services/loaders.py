"""Carga de datos del espacio para el motor (única parte que toca el ORM)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Min, Sum

from apps.core.money import ZERO, q, split_proportionally
from apps.core.periods import Frequency, IncomeInput, Period, period_for
from apps.ledger.choices import CategoryGroup, Direction, TxKind, TxStatus
from apps.ledger.models import Category, Transaction
from apps.ledger.services.balances import (
    savings_accounts_balance,
    spent_by_category,
    total_balance,
)
from apps.personal.models import (
    Commitment,
    Debt,
    EssentialEstimate,
    IncomeSource,
    PersonalProfile,
    Preference,
    SavingsGoal,
)
from apps.personal.services.availability import Availability, compute_availability
from apps.personal.services.budget_engine import build_personal_plan
from apps.personal.services.types import (
    BudgetResult,
    CommitmentInput,
    DailyMode,
    DebtInput,
    EssentialInput,
    PersonalInputs,
    Priority,
    SavingsFrequency,
    SavingsInput,
)
from apps.workspaces.models import Workspace

HISTORY_PERIODS = 2
SAVINGS_KINDS = (TxKind.TRANSFERENCIA_INTERNA, TxKind.GASTO)
DEBT_CATEGORY_NAME = "Préstamos y deudas"


def _system_category(workspace: Workspace, group: str) -> Category | None:
    category: Category | None = (
        Category.objects.for_workspace(workspace)
        .filter(group=group, is_system=True, is_archived=False)
        .order_by("created_at")
        .first()
    )
    return category


def _ref(category_id: object | None) -> str | None:
    return str(category_id) if category_id else None


def load_incomes(workspace: Workspace) -> list[IncomeInput]:
    return [
        s.to_input() for s in IncomeSource.objects.for_workspace(workspace).filter(is_active=True)
    ]


def savings_outflows(
    workspace: Workspace, category_ids: set[object], start: date | None, end: date
) -> dict[str, Decimal]:
    """Aportes de ahorro confirmados por categoría: salidas (transferencias o gastos) etiquetadas
    con la categoría de la meta."""
    qs = Transaction.objects.for_workspace(workspace).filter(
        status=TxStatus.CONFIRMADO,
        direction=Direction.OUT,
        kind__in=SAVINGS_KINDS,
        category_id__in=category_ids,
        date__lte=end,
    )
    if start:
        qs = qs.filter(date__gte=start)
    rows = qs.values("category_id").annotate(total=Sum("amount"))
    return {str(r["category_id"]): r["total"] for r in rows}


def _previous_periods(incomes: list[IncomeInput], period: Period, count: int) -> list[Period]:
    periods: list[Period] = []
    cursor = period
    for _ in range(count):
        cursor = period_for(incomes, cursor.start - timedelta(days=1))
        periods.append(cursor)
    return periods


def historical_essentials(
    workspace: Workspace, incomes: list[IncomeInput], period: Period
) -> dict[str, Decimal] | None:
    """Promedio de gasto en esenciales variables de los últimos períodos completos.

    Devuelve None si no hay al menos `HISTORY_PERIODS` períodos completos registrados.
    """
    previous = _previous_periods(incomes, period, HISTORY_PERIODS)
    first = (
        Transaction.objects.for_workspace(workspace)
        .filter(status=TxStatus.CONFIRMADO)
        .aggregate(first=Min("date"))["first"]
    )
    if first is None or first > previous[-1].start:
        return None
    essential_ids = set(
        Category.objects.for_workspace(workspace)
        .filter(group=CategoryGroup.ESENCIAL_VARIABLE)
        .values_list("id", flat=True)
    )
    totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for p in previous:
        for category_id, amount in spent_by_category(workspace, p.start, p.end).items():
            if category_id in essential_ids:
                totals[str(category_id)] += amount
    return {ref: q(total / HISTORY_PERIODS) for ref, total in totals.items()}


def load_personal_inputs(
    workspace: Workspace, today: date, opening_cash: Decimal = ZERO
) -> PersonalInputs:
    incomes = load_incomes(workspace)
    period = period_for(incomes, today)
    debt_category = (
        Category.objects.for_workspace(workspace).filter(name=DEBT_CATEGORY_NAME).first()
    )
    savings_category = _system_category(workspace, CategoryGroup.AHORRO)

    commitments = tuple(
        CommitmentInput(
            ref=str(c.pk),
            name=c.name,
            amount=c.amount,
            frequency=Frequency(c.frequency),
            due_day=c.due_day,
            category_ref=_ref(c.category_id),
            is_fixed=c.is_fixed,
        )
        for c in Commitment.objects.for_workspace(workspace).filter(is_active=True)
    )
    debts = tuple(
        DebtInput(
            ref=str(d.pk),
            name=d.name,
            installment=d.installment,
            balance=d.balance,
            due_day=d.due_day,
            end_date=d.end_date,
            interest_rate=d.interest_rate,
            category_ref=_ref(d.category_id or (debt_category.pk if debt_category else None)),
        )
        for d in Debt.objects.for_workspace(workspace)
    )

    history = historical_essentials(workspace, incomes, period)
    estimates = {
        str(e.category_id): e
        for e in EssentialEstimate.objects.for_workspace(workspace).select_related("category")
    }
    names = {
        str(pk): name
        for pk, name in Category.objects.for_workspace(workspace).values_list("id", "name")
    }
    essentials: list[EssentialInput] = []
    for ref in sorted(set(estimates) | set(history or {})):
        if history and ref in history and history[ref] > 0:
            amount, from_history = history[ref], True
        elif ref in estimates:
            amount, from_history = estimates[ref].amount, False
        else:
            continue
        essentials.append(
            EssentialInput(
                ref=ref,
                name=names[ref],
                amount=amount,
                category_ref=ref,
                from_history=from_history,
            )
        )

    goals = list(SavingsGoal.objects.for_workspace(workspace).filter(is_active=True))
    goal_category = {
        g.pk: g.category_id or (savings_category.pk if savings_category else None) for g in goals
    }
    before_period = savings_outflows(
        workspace,
        {c for c in goal_category.values() if c},
        None,
        period.start - timedelta(days=1),
    )
    saved_before = _split_by_goal(goals, goal_category, before_period)
    savings = tuple(
        SavingsInput(
            ref=str(g.pk),
            purpose=g.purpose,
            contribution_amount=g.contribution_amount,
            frequency=SavingsFrequency(g.contribution_frequency),
            daily_mode=DailyMode(g.daily_mode),
            selected_weekdays=frozenset(g.selected_weekdays or ()),
            target_amount=g.target_amount,
            saved_so_far=g.saved_initial + saved_before.get(g.pk, ZERO),
            deadline=g.deadline,
            category_ref=_ref(goal_category[g.pk]),
        )
        for g in goals
    )

    profile = PersonalProfile.objects.filter(workspace=workspace).first()
    preferences = {
        str(p.category_id): Priority(p.priority)
        for p in Preference.objects.for_workspace(workspace)
    }
    return PersonalInputs(
        period=period,
        incomes=tuple(incomes),
        commitments=commitments,
        debts=debts,
        essentials=tuple(essentials),
        savings=savings,
        discretionary_wish=profile.discretionary_wish if profile else None,
        reserve_pct=profile.reserve_pct if profile else Decimal("0.10"),
        preferences=preferences,
        opening_cash=opening_cash,
    )


def _split_by_goal(
    goals: list[SavingsGoal], goal_category: dict, by_category: dict[str, Decimal]
) -> dict[object, Decimal]:
    """Reparte lo aportado a una categoría entre las metas que la comparten (según su aporte)."""
    result: dict[object, Decimal] = {}
    grouped: dict[str, list[SavingsGoal]] = defaultdict(list)
    for g in goals:
        if goal_category[g.pk]:
            grouped[str(goal_category[g.pk])].append(g)
    for ref, members in grouped.items():
        amount = by_category.get(ref, ZERO)
        parts = split_proportionally(amount, [m.contribution_amount for m in members])
        result.update({m.pk: part for m, part in zip(members, parts, strict=True)})
    return result


def current_plan(workspace: Workspace, today: date) -> BudgetResult:
    return build_personal_plan(load_personal_inputs(workspace, today))


def workspace_availability(
    workspace: Workspace, today: date, plan: BudgetResult | None = None
) -> Availability:
    plan = plan or build_personal_plan(
        load_personal_inputs(workspace, today), with_alternatives=False
    )
    start = plan.period.start
    spent = {
        str(k): v for k, v in spent_by_category(workspace, start, today).items() if k is not None
    }
    savings_refs = {
        item.category_ref for item in plan.scheduled if item.kind == "ahorro" and item.category_ref
    }
    contributed = savings_outflows(workspace, set(savings_refs), start, today)
    return compute_availability(
        plan,
        today,
        in_accounts=total_balance(workspace, as_of=today),
        spent_by_category=spent,
        savings_contributed=sum(contributed.values(), ZERO),
        in_savings_accounts=savings_accounts_balance(workspace, as_of=today),
    )
