"""Motor de precios del negocio (encargo §8, docs/fase2.md §4). Funciones puras con Decimal.

Convenciones:
- Porcentajes de entrada como fracción (0.30 = 30 %); los de salida en puntos con 2 decimales
  (`30.00`), igual que `margins.py`.
- El **precio** es el precio de lista sin ITBIS. El cliente paga ese precio menos el descuento
  esperado, más el ITBIS (`gross_price`).
- La **comisión** se cobra sobre lo que realmente se vende (precio con descuento, sin ITBIS).
- El **margen** es la ganancia por unidad dividida por el precio efectivo (con descuento):
  `margen = 1 − comisión − costo / (precio × (1 − descuento))`.
  Sin comisión ni descuento: precio = costo / (1 − margen) → 600 al 30 % = 857.14.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal

from apps.core.money import ZERO, fmt, pct, q

ONE = Decimal("1")
HUNDRED = Decimal("100")


def _pct_text(fraction: Decimal) -> str:
    value = (fraction * HUNDRED).quantize(Decimal("0.01")).normalize()
    return f"{value:f} %"


def _check_fraction(name: str, value: Decimal, *, allow_one: bool = False) -> None:
    upper_ok = value <= ONE if allow_one else value < ONE
    if not (value >= ZERO and upper_ok):
        raise ValueError(
            f"{name} debe estar entre 0 % y {'100' if allow_one else 'menos de 100'} %"
        )


# ---------------------------------------------------------------------------- economía unitaria


@dataclass(frozen=True)
class UnitEconomics:
    price: Decimal  # precio de lista sin ITBIS
    effective_price: Decimal  # con el descuento aplicado
    commission: Decimal
    cost: Decimal  # costo por unidad sin comisión
    profit: Decimal  # ganancia bruta por unidad
    margin_pct: Decimal  # ganancia / precio efectivo
    markup_pct: Decimal  # ganancia / (costo + comisión)


def unit_economics(
    price: Decimal,
    cost: Decimal,
    commission_pct: Decimal = ZERO,
    discount_pct: Decimal = ZERO,
) -> UnitEconomics:
    """Lo que deja una unidad vendida a `price` con descuento y comisión."""
    if price < 0 or cost < 0:
        raise ValueError("El precio y el costo no pueden ser negativos")
    _check_fraction("La comisión", commission_pct)
    _check_fraction("El descuento", discount_pct, allow_one=True)
    effective = price * (ONE - discount_pct)
    commission = effective * commission_pct
    profit = effective - commission - cost
    return UnitEconomics(
        price=q(price),
        effective_price=q(effective),
        commission=q(commission),
        cost=q(cost),
        profit=q(profit),
        margin_pct=pct(profit, effective),
        markup_pct=pct(profit, cost + commission),
    )


# ---------------------------------------------------------------------------- precio sugerido


@dataclass(frozen=True)
class PricingInputs:
    unit_cost: Decimal  # materiales, empaque, mano de obra… (sin comisión)
    target_margin: Decimal  # fracción
    commission_pct: Decimal = ZERO
    discount_pct: Decimal = ZERO  # descuento que se suele dar
    delivery_cost: Decimal = ZERO  # por unidad, si no está ya en el costo
    tax_rate: Decimal = ZERO  # ITBIS
    prices_include_tax: bool = False  # el precio que se publica ya incluye el ITBIS
    currency: str = "DOP"

    @property
    def total_cost(self) -> Decimal:
        return self.unit_cost + self.delivery_cost

    def validate(self) -> None:
        if self.unit_cost < 0 or self.delivery_cost < 0:
            raise ValueError("Los costos no pueden ser negativos")
        _check_fraction("El margen", self.target_margin)
        _check_fraction("La comisión", self.commission_pct)
        _check_fraction("El descuento", self.discount_pct)
        _check_fraction("El impuesto", self.tax_rate)
        if self.commission_pct + self.target_margin >= ONE:
            raise ValueError("La comisión más el margen deben sumar menos de 100 %")


@dataclass(frozen=True)
class PricingResult:
    net_price: Decimal  # precio de lista sin ITBIS
    tax: Decimal
    gross_price: Decimal  # lo que ve el cliente, con ITBIS
    published_price: Decimal  # el precio a publicar según `prices_include_tax`
    minimum_price: Decimal  # sin ITBIS: cubre costo y comisión (margen 0)
    economics: UnitEconomics
    assumptions: list[str] = field(default_factory=list)


def _price_for_margin(inputs: PricingInputs, margin: Decimal) -> Decimal:
    divisor = (ONE - inputs.discount_pct) * (ONE - inputs.commission_pct - margin)
    return inputs.total_cost / divisor


def minimum_price(inputs: PricingInputs) -> Decimal:
    """Precio de lista (sin ITBIS) por debajo del cual se pierde dinero en cada unidad."""
    inputs.validate()
    return q(_price_for_margin(inputs, ZERO))


def compute_price(inputs: PricingInputs) -> PricingResult:
    """Precio sugerido para alcanzar el margen objetivo, con sus supuestos explícitos."""
    inputs.validate()
    net = q(_price_for_margin(inputs, inputs.target_margin))
    tax = q(net * inputs.tax_rate)
    gross = net + tax
    assumptions = [
        f"Costo por unidad: {fmt(inputs.unit_cost, inputs.currency)}"
        + (
            f" más entrega {fmt(inputs.delivery_cost, inputs.currency)}"
            if inputs.delivery_cost
            else ""
        )
        + ".",
        f"Margen objetivo: {_pct_text(inputs.target_margin)} de lo que realmente cobras.",
    ]
    if inputs.commission_pct:
        assumptions.append(
            f"Comisión de {_pct_text(inputs.commission_pct)} sobre el precio con descuento."
        )
    if inputs.discount_pct:
        assumptions.append(f"Descuento habitual de {_pct_text(inputs.discount_pct)}.")
    if inputs.tax_rate:
        assumptions.append(
            f"ITBIS de {_pct_text(inputs.tax_rate)}: "
            + (
                "el precio publicado ya lo incluye."
                if inputs.prices_include_tax
                else "se suma al precio al cobrar."
            )
        )
    return PricingResult(
        net_price=net,
        tax=tax,
        gross_price=gross,
        published_price=gross if inputs.prices_include_tax else net,
        minimum_price=minimum_price(inputs),
        economics=unit_economics(
            net, inputs.total_cost, inputs.commission_pct, inputs.discount_pct
        ),
        assumptions=assumptions,
    )


# ---------------------------------------------------------------------------- descuentos


@dataclass(frozen=True)
class DiscountResult:
    economics: UnitEconomics
    max_discount_pct: Decimal  # descuento con el que la ganancia llega a 0 (en puntos)


def margin_after_discount(
    price: Decimal, cost: Decimal, discount_pct: Decimal, commission_pct: Decimal = ZERO
) -> DiscountResult:
    """Cuánto deja una unidad si se da `discount_pct` y hasta dónde se puede descontar."""
    economics = unit_economics(price, cost, commission_pct, discount_pct)
    net_per_price = price * (ONE - commission_pct)
    max_discount = ZERO if net_per_price <= 0 else max(ZERO, ONE - cost / net_per_price)
    return DiscountResult(economics=economics, max_discount_pct=q(max_discount * HUNDRED))


# ---------------------------------------------------------------------------- equilibrio


@dataclass(frozen=True)
class BreakEvenResult:
    units: Decimal  # unidades enteras (redondeo hacia arriba)
    sales: Decimal  # unidades × precio
    contribution_per_unit: Decimal
    contribution_margin_pct: Decimal


def break_even_units(
    fixed_costs: Decimal,
    unit_price: Decimal,
    unit_variable_cost: Decimal,
    target_profit: Decimal = ZERO,
) -> BreakEvenResult | None:
    """Unidades para cubrir los gastos fijos (y la ganancia objetivo, si se indica).

    `None` si cada unidad no deja nada para cubrir gastos: no hay equilibrio posible.
    """
    if fixed_costs < 0 or target_profit < 0:
        raise ValueError("Los gastos fijos y la ganancia objetivo no pueden ser negativos")
    contribution = unit_price - unit_variable_cost
    if contribution <= 0:
        return None
    units = ((fixed_costs + target_profit) / contribution).to_integral_value(rounding=ROUND_CEILING)
    return BreakEvenResult(
        units=units,
        sales=q(units * unit_price),
        contribution_per_unit=q(contribution),
        contribution_margin_pct=pct(contribution, unit_price),
    )


# ---------------------------------------------------------------------------- sensibilidad


@dataclass(frozen=True)
class SensitivityResult:
    increase_pct: Decimal  # en puntos
    old_cost: Decimal
    new_cost: Decimal
    before: UnitEconomics  # al precio actual con el costo anterior
    after: UnitEconomics  # al precio actual con el costo nuevo
    price_to_keep_margin: Decimal  # precio de lista sin ITBIS
    price_change_pct: Decimal  # en puntos, respecto del precio actual


def supplier_increase(
    inputs: PricingInputs, current_price: Decimal, increase_pct: Decimal
) -> SensitivityResult:
    """Qué pasa si el proveedor sube `increase_pct` (fracción) el costo de los materiales.

    La entrega no cambia. El precio para mantener el margen usa el margen actual (no el objetivo).
    """
    if increase_pct <= -ONE:
        raise ValueError("El aumento no puede bajar el costo a cero o menos")
    before = unit_economics(
        current_price, inputs.total_cost, inputs.commission_pct, inputs.discount_pct
    )
    new_unit_cost = inputs.unit_cost * (ONE + increase_pct)
    new_total = new_unit_cost + inputs.delivery_cost
    after = unit_economics(current_price, new_total, inputs.commission_pct, inputs.discount_pct)
    current_margin = max(ZERO, before.margin_pct / HUNDRED)
    keep_inputs = PricingInputs(
        unit_cost=new_unit_cost,
        delivery_cost=inputs.delivery_cost,
        target_margin=current_margin,
        commission_pct=inputs.commission_pct,
        discount_pct=inputs.discount_pct,
    )
    keep_inputs.validate()
    keep_price = q(_price_for_margin(keep_inputs, current_margin))
    return SensitivityResult(
        increase_pct=q(increase_pct * HUNDRED),
        old_cost=q(inputs.total_cost),
        new_cost=q(new_total),
        before=before,
        after=after,
        price_to_keep_margin=keep_price,
        price_change_pct=pct(keep_price - current_price, current_price),
    )


# ---------------------------------------------------------------------------- volumen y margen


@dataclass(frozen=True)
class ProductStats:
    name: str
    units: Decimal
    sales: Decimal  # sin ITBIS
    gross_profit: Decimal
    ref: str = ""  # identificador del producto (para enlazar en la interfaz)


QUADRANT_ADVICE = {
    "estrella": "Vende mucho y deja buen margen: cuídalo y no lo descuentes sin necesidad.",
    "vende_mucho_deja_poco": "Vende mucho pero deja poco: revisa su precio o su costo primero.",
    "deja_mucho_vende_poco": "Deja buen margen pero se vende poco: dale más visibilidad.",
    "revisar": "Se vende poco y deja poco: evalúa si vale la pena mantenerlo.",
}


@dataclass(frozen=True)
class MatrixCell:
    stats: ProductStats
    margin_pct: Decimal
    profit_share_pct: Decimal  # parte de la ganancia bruta total
    high_volume: bool
    high_margin: bool
    quadrant: str
    advice: str


def volume_margin_matrix(
    products: list[ProductStats], target_margin: Decimal | None = None
) -> list[MatrixCell]:
    """Clasifica productos por volumen (frente al promedio) y margen (frente al objetivo o, si
    no hay objetivo, al margen global). Ordenados por ganancia bruta, de mayor a menor."""
    if not products:
        return []
    avg_units = sum((p.units for p in products), ZERO) / len(products)
    total_sales = sum((p.sales for p in products), ZERO)
    total_profit = sum((p.gross_profit for p in products), ZERO)
    threshold = (
        q(target_margin * HUNDRED) if target_margin is not None else pct(total_profit, total_sales)
    )
    cells = []
    for p in sorted(products, key=lambda s: (-s.gross_profit, s.name)):
        margin = pct(p.gross_profit, p.sales)
        high_volume = p.units > 0 and p.units >= avg_units
        high_margin = p.sales > 0 and margin >= threshold
        if high_volume and high_margin:
            quadrant = "estrella"
        elif high_volume:
            quadrant = "vende_mucho_deja_poco"
        elif high_margin:
            quadrant = "deja_mucho_vende_poco"
        else:
            quadrant = "revisar"
        cells.append(
            MatrixCell(
                stats=p,
                margin_pct=margin,
                profit_share_pct=pct(p.gross_profit, total_profit) if total_profit > 0 else ZERO,
                high_volume=high_volume,
                high_margin=high_margin,
                quadrant=quadrant,
                advice=QUADRANT_ADVICE[quadrant],
            )
        )
    return cells


# ---------------------------------------------------------------------------- servicios


@dataclass(frozen=True)
class CapacityResult:
    max_units: int  # servicios que caben en las horas disponibles
    max_sales: Decimal  # techo de ventas del mes
    max_gross_profit: Decimal
    price_per_hour: Decimal
    profit_per_hour: Decimal


def service_capacity(
    labor_minutes: int, hours_available: int, price: Decimal, unit_cost: Decimal = ZERO
) -> CapacityResult:
    """Techo de ingresos de un servicio: el tiempo es el límite, no la demanda."""
    if labor_minutes <= 0:
        raise ValueError("Indica cuántos minutos toma el servicio")
    if hours_available < 0:
        raise ValueError("Las horas disponibles no pueden ser negativas")
    max_units = math.floor(Decimal(hours_available * 60) / labor_minutes)
    per_hour = Decimal(60) / Decimal(labor_minutes)
    profit = price - unit_cost
    return CapacityResult(
        max_units=max_units,
        max_sales=q(price * max_units),
        max_gross_profit=q(profit * max_units),
        price_per_hour=q(price * per_hour),
        profit_per_hour=q(profit * per_hour),
    )
