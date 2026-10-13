"""Arma las entradas del motor de precios desde los modelos del negocio."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from apps.business.services.product_cost import cost_basis

from .engine import PricingInputs

if TYPE_CHECKING:
    from apps.business.models import BusinessProfile, Product


def inputs_for_product(
    product: Product,
    profile: BusinessProfile | None,
    target_margin: Decimal,
    discount_pct: Decimal = Decimal("0"),
) -> PricingInputs:
    """Separa la comisión (porcentaje) del resto del costo: el motor la calcula sobre el precio.

    El costo base sale de `cost_basis`: promedio si tiene inventario, receta + componentes si es
    elaborado, componentes, o el costo escrito a mano.
    """
    base_cost, commission = cost_basis(product)
    return PricingInputs(
        unit_cost=base_cost,
        target_margin=target_margin,
        commission_pct=commission,
        discount_pct=discount_pct,
        tax_rate=profile.tax_rate_itbis if profile else Decimal("0"),
        prices_include_tax=profile.prices_include_tax if profile else False,
        currency=product.workspace.currency,
    )
