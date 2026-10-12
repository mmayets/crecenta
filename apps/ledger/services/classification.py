"""Qué cuenta como gasto, qué como ingreso y qué es neutro.

Reglas (docs/decisiones.md §39):
- Transferencias internas y retiros de efectivo mueven dinero entre cuentas propias: no son gasto
  ni ingreso.
- Un préstamo recibido aumenta el efectivo pero no es ingreso ni ganancia; uno otorgado no es gasto.
- Un pago de deuda consume presupuesto personal (cuota comprometida), por eso se cuenta como gasto
  en el seguimiento del presupuesto. En el negocio (Fase 2) el abono a capital no es gasto del
  resultado; se trata en los servicios de negocio.
"""

from __future__ import annotations

from decimal import Decimal

from apps.ledger.choices import Direction, TxKind

INCOME_KINDS = frozenset({TxKind.INGRESO, TxKind.VENTA})
EXPENSE_KINDS = frozenset({TxKind.GASTO, TxKind.PAGO_DEUDA, TxKind.COMPRA_INVENTARIO})
TRANSFER_KINDS = frozenset({TxKind.TRANSFERENCIA_INTERNA, TxKind.RETIRO_EFECTIVO})
NEUTRAL_KINDS = TRANSFER_KINDS | {TxKind.PRESTAMO}

_BOTH = frozenset({Direction.IN, Direction.OUT})


def allowed_directions(kind: str) -> frozenset[str]:
    if kind in INCOME_KINDS:
        return frozenset({Direction.IN})
    if kind in EXPENSE_KINDS:
        return frozenset({Direction.OUT})
    if kind in NEUTRAL_KINDS:
        return _BOTH
    raise ValueError(f"Tipo de movimiento desconocido: {kind}")


def is_income_kind(kind: str) -> bool:
    return kind in INCOME_KINDS


def counts_as_income(kind: str, direction: str) -> bool:
    return kind in INCOME_KINDS and direction == Direction.IN


def counts_as_expense(kind: str, direction: str) -> bool:
    return kind in EXPENSE_KINDS and direction == Direction.OUT


def is_transfer(kind: str) -> bool:
    return kind in TRANSFER_KINDS


def signed_amount(amount: Decimal, direction: str) -> Decimal:
    """Monto con signo según el sentido (+ entrada, − salida)."""
    if direction == Direction.IN:
        return amount
    if direction == Direction.OUT:
        return -amount
    raise ValueError(f"Sentido desconocido: {direction}")
