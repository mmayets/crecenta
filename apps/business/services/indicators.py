"""Indicadores del período del negocio (funciones puras; docs/fase2.md §1).

Separa tres cosas que el encargo pide no mezclar:
- **Resultado**: ventas (líneas sin ITBIS) − costo de lo vendido (costo guardado al vender)
  = ganancia bruta; − gastos operativos = resultado operativo.
- **Flujo de efectivo**: entradas y salidas reales de las cuentas del negocio.
- **Lo pendiente**: cuentas por cobrar y por pagar abiertas.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from apps.core.money import ZERO, fmt, pct, q
from apps.pricing.services.engine import ProductStats

HUNDRED = Decimal("100")
WEEKS_PER_MONTH = Decimal("52") / Decimal("12")
MONTHLY_FACTOR = {"mensual": Decimal("1"), "quincenal": Decimal("2"), "semanal": WEEKS_PER_MONTH}


@dataclass(frozen=True)
class SoldLine:
    product_ref: str  # id del producto ("" si es una línea libre)
    name: str
    qty: Decimal
    net_amount: Decimal  # sin ITBIS, con descuento
    unit_cost: Decimal  # costo guardado al vender


@dataclass(frozen=True)
class ExpensePlan:
    """Gasto operativo previsto (para equilibrio y compromisos)."""

    ref: str
    name: str
    amount: Decimal
    frequency: str  # mensual | quincenal | semanal
    due_day: int | None = None
    is_reducible: bool = False

    @property
    def monthly_amount(self) -> Decimal:
        return self.amount * MONTHLY_FACTOR.get(self.frequency, Decimal("1"))


@dataclass(frozen=True)
class GoalInputs:
    target_sales: Decimal | None = None
    target_margin: Decimal | None = None  # fracción
    target_profit: Decimal | None = None
    cash_reserve: Decimal = ZERO


@dataclass(frozen=True)
class BusinessPeriodInputs:
    start: datetime.date
    end: datetime.date
    currency: str
    lines: list[SoldLine]
    tax_collected: Decimal = ZERO
    untracked_sales: Decimal = ZERO  # movimientos `venta` sin venta detallada (costo desconocido)
    other_income: Decimal = ZERO  # ingresos que no son ventas
    operating_expenses: Decimal = ZERO  # gastos del resultado (grupo gasto operativo o sin grupo)
    uncategorized_expenses: Decimal = ZERO  # parte de lo anterior sin categoría
    variable_costs_paid: Decimal = ZERO  # comisiones, entregas, materiales pagados (solo efectivo)
    cash_in: Decimal = ZERO
    cash_out: Decimal = ZERO
    receivables_open: Decimal = ZERO
    receivables_overdue: Decimal = ZERO
    payables_open: Decimal = ZERO
    payables_overdue: Decimal = ZERO
    expense_plan: list[ExpensePlan] = field(default_factory=list)
    goal: GoalInputs = field(default_factory=GoalInputs)


@dataclass(frozen=True)
class ProductMargin:
    ref: str
    name: str
    units: Decimal
    sales: Decimal
    cogs: Decimal
    gross_profit: Decimal
    margin_pct: Decimal

    def as_stats(self) -> ProductStats:
        return ProductStats(
            name=self.name,
            units=self.units,
            sales=self.sales,
            gross_profit=self.gross_profit,
            ref=self.ref,
        )


@dataclass(frozen=True)
class GoalProgress:
    sales_pct: Decimal | None  # % de la meta de ventas alcanzado
    margin_gap_pct: Decimal | None  # puntos de margen sobre (+) o bajo (−) el objetivo
    profit_pct: Decimal | None  # % de la meta de ganancia alcanzado


@dataclass(frozen=True)
class PeriodIndicators:
    start: datetime.date
    end: datetime.date
    sales: Decimal
    cogs: Decimal
    gross_profit: Decimal
    gross_margin_pct: Decimal
    operating_expenses: Decimal
    operating_result: Decimal
    other_income: Decimal
    cash_in: Decimal
    cash_out: Decimal
    net_cash_flow: Decimal
    tax_collected: Decimal
    receivables: Decimal
    receivables_overdue: Decimal
    payables: Decimal
    payables_overdue: Decimal
    variable_costs_paid: Decimal
    fixed_costs_month: Decimal  # gastos operativos previstos al mes
    break_even_sales: Decimal | None  # ventas del mes que cubren los gastos previstos
    by_product: list[ProductMargin]
    goal: GoalProgress
    notes: list[str]  # datos faltantes o estimados


def product_margins(lines: list[SoldLine]) -> list[ProductMargin]:
    """Ventas, costo y ganancia por producto, de mayor a menor ganancia."""
    groups: dict[str, list[SoldLine]] = defaultdict(list)
    for line in lines:
        groups[line.product_ref or f"libre:{line.name}"].append(line)
    result = []
    for key, items in groups.items():
        sales = sum((i.net_amount for i in items), ZERO)
        cogs = q(sum((i.qty * i.unit_cost for i in items), ZERO))
        result.append(
            ProductMargin(
                ref="" if key.startswith("libre:") else key,
                name=items[0].name,
                units=sum((i.qty for i in items), ZERO),
                sales=sales,
                cogs=cogs,
                gross_profit=sales - cogs,
                margin_pct=pct(sales - cogs, sales),
            )
        )
    return sorted(result, key=lambda m: (-m.gross_profit, m.name))


def _ratio(part: Decimal, target: Decimal | None) -> Decimal | None:
    if target is None or target <= 0:
        return None
    return pct(part, target)


def compute_indicators(inputs: BusinessPeriodInputs) -> PeriodIndicators:
    by_product = product_margins(inputs.lines)
    sales = sum((m.sales for m in by_product), ZERO) + inputs.untracked_sales
    cogs = sum((m.cogs for m in by_product), ZERO)
    gross = sales - cogs
    gross_margin = pct(gross, sales)
    result = gross - inputs.operating_expenses
    fixed_month = q(sum((e.monthly_amount for e in inputs.expense_plan), ZERO))

    break_even: Decimal | None = None
    contribution_ratio = gross / sales if sales > 0 else ZERO
    if contribution_ratio > 0:
        break_even = q(fixed_month / contribution_ratio)

    goal = inputs.goal
    progress = GoalProgress(
        sales_pct=_ratio(sales, goal.target_sales),
        margin_gap_pct=(
            q(gross_margin - goal.target_margin * HUNDRED)
            if goal.target_margin is not None and sales > 0
            else None
        ),
        profit_pct=_ratio(result, goal.target_profit),
    )

    notes: list[str] = []
    if inputs.untracked_sales > 0:
        notes.append(
            f"{fmt(inputs.untracked_sales, inputs.currency)} en ventas registradas sin detalle de "
            "producto: se cuentan como venta sin costo, así que la ganancia puede ser menor."
        )
    if inputs.uncategorized_expenses > 0:
        notes.append(
            f"{fmt(inputs.uncategorized_expenses, inputs.currency)} en gastos sin categoría: se "
            "tratan como gastos operativos."
        )
    if any(line.unit_cost == 0 and line.net_amount > 0 for line in inputs.lines):
        notes.append("Hay ventas de productos sin costo registrado: su ganancia está sobrestimada.")
    if not inputs.expense_plan:
        notes.append(
            "No hay gastos fijos registrados: no se puede calcular el punto de equilibrio."
        )

    return PeriodIndicators(
        start=inputs.start,
        end=inputs.end,
        sales=sales,
        cogs=cogs,
        gross_profit=gross,
        gross_margin_pct=gross_margin,
        operating_expenses=inputs.operating_expenses,
        operating_result=result,
        other_income=inputs.other_income,
        cash_in=inputs.cash_in,
        cash_out=inputs.cash_out,
        net_cash_flow=inputs.cash_in - inputs.cash_out,
        tax_collected=inputs.tax_collected,
        receivables=inputs.receivables_open,
        receivables_overdue=inputs.receivables_overdue,
        payables=inputs.payables_open,
        payables_overdue=inputs.payables_overdue,
        variable_costs_paid=inputs.variable_costs_paid,
        fixed_costs_month=fixed_month,
        break_even_sales=break_even if inputs.expense_plan else None,
        by_product=by_product,
        goal=progress,
        notes=notes,
    )
