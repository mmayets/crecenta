"""Totales de una venta (función pura). El ITBIS se calcula sobre el total, no por línea, para que
subtotal + ITBIS = total al centavo."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from apps.core.money import ZERO, q, split_proportionally

ONE = Decimal("1")


@dataclass(frozen=True)
class LineInput:
    qty: Decimal
    unit_price: Decimal  # como se cobra (con ITBIS si `prices_include_tax`)
    discount_pct: Decimal = ZERO  # fracción


@dataclass(frozen=True)
class SaleTotals:
    subtotal: Decimal  # sin ITBIS: lo que cuenta como venta
    tax: Decimal
    total: Decimal  # lo que paga el cliente
    line_nets: list[Decimal]  # importe sin ITBIS de cada línea; suman `subtotal`


def line_amount(line: LineInput) -> Decimal:
    if line.qty <= 0:
        raise ValueError("La cantidad debe ser mayor que cero")
    if line.unit_price < 0:
        raise ValueError("El precio no puede ser negativo")
    if not ZERO <= line.discount_pct <= ONE:
        raise ValueError("El descuento debe estar entre 0 % y 100 %")
    return q(line.qty * line.unit_price * (ONE - line.discount_pct))


def sale_totals(
    lines: Sequence[LineInput], tax_rate: Decimal, *, prices_include_tax: bool
) -> SaleTotals:
    if not lines:
        raise ValueError("La venta necesita al menos una línea")
    if tax_rate < 0:
        raise ValueError("El impuesto no puede ser negativo")
    amounts = [line_amount(line) for line in lines]
    charged = sum(amounts, ZERO)
    if prices_include_tax:
        subtotal = q(charged / (ONE + tax_rate))
        tax = charged - subtotal
        nets = split_proportionally(subtotal, amounts)
        return SaleTotals(subtotal=subtotal, tax=tax, total=charged, line_nets=nets)
    tax = q(charged * tax_rate)
    return SaleTotals(subtotal=charged, tax=tax, total=charged + tax, line_nets=amounts)
