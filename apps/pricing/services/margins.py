"""Precios por margen y por recargo (markup). Funciones puras con Decimal (encargo §8).

- Margen bruto objetivo:  precio = costo / (1 − margen)   → 600 al 30 % = RD$857.14
- Recargo (markup):       precio = costo × (1 + recargo)  → 600 al 30 % = RD$780.00
Margen y recargo no son lo mismo: un margen del 30 % equivale a un recargo del 42.86 %.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from apps.core.money import ZERO, pct, q

ONE = Decimal("1")


@dataclass(frozen=True)
class PriceResult:
    cost: Decimal
    price: Decimal
    gross_profit: Decimal
    margin_pct: Decimal  # ganancia / precio
    markup_pct: Decimal  # ganancia / costo
    method: str  # margen | recargo


@dataclass(frozen=True)
class TaxBreakdown:
    net: Decimal  # precio sin ITBIS
    tax: Decimal
    gross: Decimal  # precio con ITBIS


def _result(cost: Decimal, price: Decimal, method: str) -> PriceResult:
    price = q(price)
    profit = price - cost
    return PriceResult(
        cost=cost,
        price=price,
        gross_profit=profit,
        margin_pct=pct(profit, price),
        markup_pct=pct(profit, cost),
        method=method,
    )


def price_from_margin(cost: Decimal, margin: Decimal) -> PriceResult:
    """`margin` como fracción (0.30 = 30 %). Debe ser ≥ 0 y < 1."""
    if cost < 0:
        raise ValueError("El costo no puede ser negativo")
    if not ZERO <= margin < ONE:
        raise ValueError("El margen debe estar entre 0 % y menos de 100 %")
    return _result(cost, cost / (ONE - margin), "margen")


def price_from_markup(cost: Decimal, markup: Decimal) -> PriceResult:
    """`markup` como fracción (0.30 = 30 % sobre el costo)."""
    if cost < 0:
        raise ValueError("El costo no puede ser negativo")
    if markup < 0:
        raise ValueError("El recargo no puede ser negativo")
    return _result(cost, cost * (ONE + markup), "recargo")


def margin_vs_markup(cost: Decimal, price: Decimal) -> tuple[Decimal, Decimal]:
    """(margen %, recargo %) de un precio dado."""
    profit = price - cost
    return pct(profit, price), pct(profit, cost)


def with_tax(price: Decimal, rate: Decimal, *, included: bool) -> TaxBreakdown:
    """Desglose del ITBIS/IVA. Si `included`, el precio ya trae el impuesto."""
    if included:
        net = q(price / (ONE + rate))
        return TaxBreakdown(net=net, tax=q(price) - net, gross=q(price))
    tax = q(price * rate)
    return TaxBreakdown(net=q(price), tax=tax, gross=q(price) + tax)
