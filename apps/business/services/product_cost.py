"""Costo de un producto según cómo se maneja (Fase 4):

- con inventario (mercancía): costo promedio;
- con receta (elaborado con insumos): Σ cantidad × costo promedio de cada insumo, más los
  componentes de costo que no son insumos (empaque, entrega); la comisión va aparte, sobre el
  precio;
- con componentes: su suma (Fase 2);
- si no, el costo escrito a mano.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from apps.core.money import ZERO, q

from .costs import ComponentInput, unit_cost

if TYPE_CHECKING:
    from apps.business.models import Product


def recipe_cost(product: Product) -> Decimal | None:
    """Costo de los insumos de una unidad, o None si el producto no tiene receta."""
    items = list(product.recipe.select_related("supply"))
    if not items:
        return None
    return sum((item.qty * item.supply.average_cost for item in items), ZERO)


def cost_basis(product: Product) -> tuple[Decimal, Decimal]:
    """(costo por unidad sin comisión, comisión como fracción del precio)."""
    if product.tracks_inventory:
        return Decimal(product.average_cost), ZERO
    components = [ComponentInput(c.type, c.amount) for c in product.components.all()]
    breakdown = unit_cost(product.price, components) if components else None
    fixed = breakdown.fixed_part if breakdown else ZERO
    commission = breakdown.commission_pct if breakdown else ZERO
    from_recipe = recipe_cost(product)
    if from_recipe is not None:
        return from_recipe + fixed, commission
    if breakdown is not None:
        return fixed, commission
    return product.unit_cost, ZERO


def current_unit_cost(product: Product, price: Decimal | None = None) -> Decimal:
    """Costo por unidad (con la comisión sobre `price`, por defecto el precio del producto)."""
    base, commission = cost_basis(product)
    return q(base + (product.price if price is None else price) * commission)
