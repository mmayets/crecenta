"""Costo unitario a partir de sus componentes (función pura + cargador).

La comisión es un porcentaje del precio de venta; los demás componentes son montos por unidad.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from apps.core.money import ZERO, q

if TYPE_CHECKING:
    from apps.business.models import Product

COMMISSION = "comision_pct"


@dataclass(frozen=True)
class ComponentInput:
    type: str
    amount: Decimal  # monto por unidad, o fracción del precio si es comisión


@dataclass(frozen=True)
class UnitCostBreakdown:
    fixed_part: Decimal  # suma de componentes en monto
    commission_pct: Decimal  # suma de comisiones (fracción)
    commission_amount: Decimal  # comisión sobre el precio dado
    unit_cost: Decimal  # redondeado al centavo


def unit_cost(price: Decimal, components: Iterable[ComponentInput]) -> UnitCostBreakdown:
    fixed = ZERO
    commission = ZERO
    for c in components:
        if c.type == COMMISSION:
            commission += c.amount
        else:
            fixed += c.amount
    commission_amount = price * commission
    return UnitCostBreakdown(
        fixed_part=fixed,
        commission_pct=commission,
        commission_amount=q(commission_amount),
        unit_cost=q(fixed + commission_amount),
    )


def refresh_unit_cost(product: Product) -> Decimal:
    """Recalcula y guarda el costo unitario si el producto tiene componentes o receta (con la
    receta, el costo de los insumos al promedio de hoy)."""
    if product.recipe.exists():
        from .product_cost import current_unit_cost

        new: Decimal = current_unit_cost(product)
        product.unit_cost = new
        product.save(update_fields=["unit_cost", "updated_at"])
        return new
    components = [ComponentInput(c.type, c.amount) for c in product.components.all()]
    if not components:
        current: Decimal = product.unit_cost
        return current
    new_cost = unit_cost(product.price, components).unit_cost
    product.unit_cost = new_cost
    product.save(update_fields=["unit_cost", "updated_at"])
    return new_cost
