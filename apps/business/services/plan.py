"""Plan de negocio del mes (función pura; encargo §8 y docs/fase2.md §4).

Con el volumen esperado por producto calcula ventas, costo, ganancia bruta, gastos operativos y
resultado; el equilibrio y las ventas necesarias para la ganancia objetivo; el flujo de caja por
fechas hasta fin de mes y el retiro máximo del propietario. Las alternativas (subir precio, bajar
costo, vender más del producto con mejor margen, reducir gastos reducibles, posponer el retiro) se
recalculan con este mismo motor: la IA solo las explica.
"""

from __future__ import annotations

import datetime
import math
from dataclasses import dataclass, field, replace
from decimal import Decimal
from enum import StrEnum

from apps.core.money import ZERO, fmt, pct, q, split_evenly
from apps.pricing.services.engine import PricingInputs, compute_price, unit_economics

from .cash import (
    CashItem,
    CashProjection,
    OpenDebt,
    cash_projection,
    commitments,
    expected_inflows,
)
from .indicators import ExpensePlan

HUNDRED = Decimal("100")
COST_CUT = Decimal("0.10")  # bajar 10 % el costo del producto que más pesa
MORE_UNITS = Decimal("0.20")  # vender 20 % más del producto con mejor margen
EXPENSE_CUT = Decimal("0.20")  # recortar 20 % los gastos marcados como reducibles


class PlanStatus(StrEnum):
    VIABLE = "viable"
    AJUSTADO = "ajustado"
    NO_VIABLE = "no_viable"


@dataclass(frozen=True)
class PlanProduct:
    ref: str
    name: str
    price: Decimal  # sin ITBIS
    base_cost: Decimal  # costo por unidad sin comisión
    commission_pct: Decimal = ZERO
    expected_units: Decimal = ZERO
    units_estimated: bool = False  # tomado de lo vendido el mes anterior
    is_service: bool = False
    labor_minutes: int | None = None


@dataclass(frozen=True)
class BusinessPlanInputs:
    start: datetime.date
    end: datetime.date
    today: datetime.date
    currency: str
    products: tuple[PlanProduct, ...]
    expenses: tuple[ExpensePlan, ...] = ()
    cash_now: Decimal = ZERO
    receivables: tuple[OpenDebt, ...] = ()
    payables: tuple[OpenDebt, ...] = ()
    paid_this_month: frozenset[str] = frozenset()
    target_margin: Decimal | None = None  # fracción
    target_profit: Decimal | None = None
    cash_reserve: Decimal = ZERO
    planned_withdrawal: Decimal = ZERO
    hours_available: int | None = None


@dataclass(frozen=True)
class ProductPlan:
    ref: str
    name: str
    units: Decimal
    price: Decimal
    unit_cost: Decimal  # costo + comisión por unidad
    sales: Decimal
    cogs: Decimal
    gross_profit: Decimal
    margin_pct: Decimal
    units_estimated: bool


@dataclass(frozen=True)
class Change:
    concept: str
    before: Decimal
    after: Decimal


@dataclass(frozen=True)
class Alternative:
    code: str
    name: str
    description: str
    changes: list[Change]
    status: PlanStatus
    operating_result: Decimal
    lowest_balance: Decimal
    result_gain: Decimal  # mejora del resultado del mes
    cash_gain: Decimal  # mejora del saldo más bajo del mes

    @property
    def improvement(self) -> Decimal:
        return self.result_gain if self.result_gain > 0 else self.cash_gain


@dataclass(frozen=True)
class BusinessPlanResult:
    status: PlanStatus
    reasons: list[str]
    products: list[ProductPlan]
    sales: Decimal
    cogs: Decimal
    gross_profit: Decimal
    gross_margin_pct: Decimal
    operating_expenses: Decimal
    operating_result: Decimal
    break_even_sales: Decimal | None
    sales_for_target_profit: Decimal | None
    projection: CashProjection
    max_withdrawal: Decimal
    planned_withdrawal: Decimal
    capacity_minutes: int | None
    used_minutes: int
    assumptions: list[str]
    alternatives: list[Alternative] = field(default_factory=list)


def _product_plan(p: PlanProduct) -> ProductPlan:
    eco = unit_economics(p.price, p.base_cost, p.commission_pct)
    unit_cost = p.base_cost + p.price * p.commission_pct
    sales = q(p.price * p.expected_units)
    cogs = q(unit_cost * p.expected_units)
    return ProductPlan(
        ref=p.ref,
        name=p.name,
        units=p.expected_units,
        price=p.price,
        unit_cost=q(unit_cost),
        sales=sales,
        cogs=cogs,
        gross_profit=sales - cogs,
        margin_pct=eco.margin_pct,
        units_estimated=p.units_estimated,
    )


def _sales_cash(
    gross_profit: Decimal, start: datetime.date, end: datetime.date, today: datetime.date
) -> list[CashItem]:
    """La ganancia bruta del plan entra pareja en los días que quedan del mes (proyección)."""
    first = max(today, start)
    if first > end or gross_profit == 0:
        return []
    total_days = (end - start).days + 1
    remaining = (end - first).days + 1
    share = q(gross_profit * remaining / total_days)
    kind = "cxc" if share > 0 else "gasto"
    label = "Ganancia de las ventas del plan" if share > 0 else "Pérdida de las ventas del plan"
    return [
        CashItem(first + datetime.timedelta(days=i), abs(amount), label, kind)
        for i, amount in enumerate(split_evenly(share, remaining))
        if amount != 0
    ]


def build_business_plan(
    inputs: BusinessPlanInputs, *, with_alternatives: bool = True
) -> BusinessPlanResult:
    products = [_product_plan(p) for p in inputs.products]
    sales = sum((p.sales for p in products), ZERO)
    cogs = sum((p.cogs for p in products), ZERO)
    gross = sales - cogs
    opex = q(sum((e.monthly_amount for e in inputs.expenses), ZERO))
    result = gross - opex
    ratio = gross / sales if sales > 0 else ZERO
    break_even = q(opex / ratio) if ratio > 0 and inputs.expenses else None
    for_target = (
        q((opex + inputs.target_profit) / ratio)
        if ratio > 0 and inputs.target_profit is not None
        else None
    )

    today = max(inputs.today, inputs.start)
    outflows = commitments(
        today, inputs.end, list(inputs.payables), list(inputs.expenses), inputs.paid_this_month
    )
    inflows = [
        *expected_inflows(today, inputs.end, list(inputs.receivables)),
        *_sales_cash(gross, inputs.start, inputs.end, inputs.today),
    ]
    loss_items = [i for i in inflows if i.kind != "cxc"]
    inflows = [i for i in inflows if i.kind == "cxc"]
    outflows = sorted([*outflows, *loss_items], key=lambda i: (i.date, i.label))
    without_draw = cash_projection(inputs.cash_now, today, outflows, inflows)
    max_withdrawal = max(ZERO, q(without_draw.lowest_balance - inputs.cash_reserve))
    draw = (
        [CashItem(today, inputs.planned_withdrawal, "Retiro del propietario", "gasto")]
        if inputs.planned_withdrawal > 0
        else []
    )
    projection = cash_projection(inputs.cash_now, today, [*draw, *outflows], inflows)

    used = sum(
        (
            math.ceil(p.expected_units * p.labor_minutes)
            for p in inputs.products
            if p.is_service and p.labor_minutes
        ),
        0,
    )
    capacity = inputs.hours_available * 60 if inputs.hours_available else None

    cur = inputs.currency
    reasons: list[str] = []
    if result < 0:
        reasons.append(f"Con estas ventas el negocio pierde {fmt(-result, cur)} en el mes.")
    if projection.gaps:
        gap = projection.gaps[0]
        reasons.append(
            f"El {gap.date:%d/%m} faltarían {fmt(gap.shortfall, cur)} en efectivo"
            + (f" ({', '.join(gap.causes)})." if gap.causes else ".")
        )
    status = PlanStatus.NO_VIABLE if reasons else PlanStatus.VIABLE
    if status == PlanStatus.VIABLE:
        if inputs.target_profit is not None and result < inputs.target_profit:
            reasons.append(
                f"La ganancia del mes ({fmt(result, cur)}) no llega a la meta "
                f"({fmt(inputs.target_profit, cur)})."
            )
        margin = pct(gross, sales)
        if (
            inputs.target_margin is not None
            and sales > 0
            and margin < inputs.target_margin * HUNDRED
        ):
            reasons.append(
                f"El margen bruto ({margin} %) está bajo el objetivo "
                f"({q(inputs.target_margin * HUNDRED)} %)."
            )
        if projection.lowest_balance < inputs.cash_reserve:
            reasons.append(
                f"El efectivo bajaría a {fmt(projection.lowest_balance, cur)}, por debajo de la "
                f"reserva ({fmt(inputs.cash_reserve, cur)})."
            )
        if capacity is not None and used > capacity:
            reasons.append("Los servicios del plan necesitan más horas de las disponibles.")
        if reasons:
            status = PlanStatus.AJUSTADO

    assumptions = [
        "Ventas del mes según las unidades esperadas de cada producto, a su precio sin ITBIS.",
        "La ganancia de las ventas del plan entra pareja en los días que quedan del mes.",
        "Solo se cuentan los cobros de clientes con fecha dentro del mes.",
    ]
    if inputs.planned_withdrawal > 0:
        assumptions.append(
            f"Retiro del propietario de {fmt(inputs.planned_withdrawal, cur)} hecho hoy."
        )
    estimated = [p.name for p in inputs.products if p.units_estimated]
    if estimated:
        assumptions.append(
            "Unidades estimadas con lo vendido el mes anterior: " + ", ".join(estimated) + "."
        )

    base = BusinessPlanResult(
        status=status,
        reasons=reasons,
        products=sorted(products, key=lambda p: (-p.gross_profit, p.name)),
        sales=sales,
        cogs=cogs,
        gross_profit=gross,
        gross_margin_pct=pct(gross, sales),
        operating_expenses=opex,
        operating_result=result,
        break_even_sales=break_even,
        sales_for_target_profit=for_target,
        projection=projection,
        max_withdrawal=max_withdrawal,
        planned_withdrawal=inputs.planned_withdrawal,
        capacity_minutes=capacity,
        used_minutes=used,
        assumptions=assumptions,
    )
    if not with_alternatives:
        return base
    return replace(base, alternatives=alternatives_for(inputs, base))


# ---------------------------------------------------------------------------- alternativas

ALTERNATIVE_CODES = (
    "subir_precio",
    "bajar_costo",
    "vender_mas",
    "reducir_gastos",
    "posponer_retiro",
)


def alternative_inputs(
    inputs: BusinessPlanInputs, code: str
) -> tuple[BusinessPlanInputs, str, str, list[Change]] | None:
    """Entradas modificadas por una alternativa, su nombre, descripción y cambios. `None` si no
    aplica a este negocio."""
    cur = inputs.currency
    if code == "subir_precio":
        if inputs.target_margin is None:
            return None
        changes: list[Change] = []
        repriced: list[PlanProduct] = []
        for p in inputs.products:
            margin = unit_economics(p.price, p.base_cost, p.commission_pct).margin_pct
            if (
                p.expected_units > 0
                and margin < inputs.target_margin * HUNDRED
                and (p.commission_pct + inputs.target_margin < 1)
            ):
                new_price = compute_price(
                    PricingInputs(
                        unit_cost=p.base_cost,
                        target_margin=inputs.target_margin,
                        commission_pct=p.commission_pct,
                    )
                ).net_price
                changes.append(Change(f"Precio de {p.name}", p.price, new_price))
                repriced.append(replace(p, price=new_price))
            else:
                repriced.append(p)
        if not changes:
            return None
        target = q(inputs.target_margin * HUNDRED)
        return (
            replace(inputs, products=tuple(repriced)),
            "Subir precios al margen objetivo",
            f"Subir el precio de los productos que dejan menos del {target} % de margen.",
            changes,
        )
    if code == "bajar_costo":
        selling = [p for p in inputs.products if p.expected_units > 0 and p.base_cost > 0]
        if not selling:
            return None
        top = max(selling, key=lambda p: (p.base_cost * p.expected_units, p.name))
        new_cost = q(top.base_cost * (1 - COST_CUT))
        products = tuple(replace(p, base_cost=new_cost) if p is top else p for p in inputs.products)
        return (
            replace(inputs, products=products),
            f"Bajar el costo de {top.name}",
            f"Negociar con el proveedor o cambiar materiales para que {top.name} cueste "
            f"{fmt(new_cost, cur)} en vez de {fmt(top.base_cost, cur)} por unidad.",
            [Change(f"Costo de {top.name}", top.base_cost, new_cost)],
        )
    if code == "vender_mas":
        candidates = [
            p
            for p in inputs.products
            if p.expected_units > 0
            and unit_economics(p.price, p.base_cost, p.commission_pct).profit > 0
        ]
        if not candidates:
            return None
        best = max(
            candidates,
            key=lambda p: (
                unit_economics(p.price, p.base_cost, p.commission_pct).margin_pct,
                p.name,
            ),
        )
        new_units = Decimal(math.ceil(best.expected_units * (1 + MORE_UNITS)))
        products = tuple(
            replace(p, expected_units=new_units) if p is best else p for p in inputs.products
        )
        return (
            replace(inputs, products=products),
            f"Vender más {best.name}",
            f"{best.name} es el producto que deja mejor margen: vender {new_units:f} en vez de "
            f"{best.expected_units.normalize():f} al mes.",
            [Change(f"Unidades de {best.name}", best.expected_units, new_units)],
        )
    if code == "reducir_gastos":
        reducible = [e for e in inputs.expenses if e.is_reducible and e.amount > 0]
        if not reducible:
            return None
        changes = [Change(e.name, e.amount, q(e.amount * (1 - EXPENSE_CUT))) for e in reducible]
        new_amounts = {e.ref: c.after for e, c in zip(reducible, changes, strict=True)}
        expenses = tuple(
            replace(e, amount=new_amounts[e.ref]) if e.ref in new_amounts else e
            for e in inputs.expenses
        )
        return (
            replace(inputs, expenses=expenses),
            "Recortar gastos reducibles",
            "Bajar un 20 % los gastos que marcaste como reducibles.",
            changes,
        )
    if code == "posponer_retiro":
        if inputs.planned_withdrawal <= 0:
            return None
        return (
            replace(inputs, planned_withdrawal=ZERO),
            "Posponer el retiro del propietario",
            "Dejar el retiro para el próximo mes, cuando haya entrado el dinero de las ventas.",
            [Change("Retiro del propietario", inputs.planned_withdrawal, ZERO)],
        )
    raise ValueError(f"Alternativa desconocida: {code}")


def alternatives_for(inputs: BusinessPlanInputs, base: BusinessPlanResult) -> list[Alternative]:
    if base.status == PlanStatus.VIABLE:
        return []
    found = []
    for code in ALTERNATIVE_CODES:
        modified = alternative_inputs(inputs, code)
        if modified is None:
            continue
        new_inputs, name, description, changes = modified
        new = build_business_plan(new_inputs, with_alternatives=False)
        alt = Alternative(
            code=code,
            name=name,
            description=description,
            changes=changes,
            status=new.status,
            operating_result=new.operating_result,
            lowest_balance=new.projection.lowest_balance,
            result_gain=new.operating_result - base.operating_result,
            cash_gain=new.projection.lowest_balance - base.projection.lowest_balance,
        )
        if alt.improvement > 0:
            found.append(alt)
    return sorted(found, key=lambda a: (-a.improvement, a.code))
