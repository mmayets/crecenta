from decimal import Decimal

import pytest

from apps.ledger.choices import Direction, TxKind
from apps.ledger.services.classification import (
    allowed_directions,
    counts_as_expense,
    counts_as_income,
    is_transfer,
    signed_amount,
)


@pytest.mark.parametrize(
    ("kind", "direction", "expense", "income"),
    [
        (TxKind.GASTO, Direction.OUT, True, False),
        (TxKind.PAGO_DEUDA, Direction.OUT, True, False),
        (TxKind.COMPRA_INVENTARIO, Direction.OUT, True, False),
        (TxKind.INGRESO, Direction.IN, False, True),
        (TxKind.VENTA, Direction.IN, False, True),
        # Neutros: no son gasto ni ingreso en ningún sentido.
        (TxKind.TRANSFERENCIA_INTERNA, Direction.OUT, False, False),
        (TxKind.TRANSFERENCIA_INTERNA, Direction.IN, False, False),
        (TxKind.RETIRO_EFECTIVO, Direction.OUT, False, False),
        (TxKind.RETIRO_EFECTIVO, Direction.IN, False, False),
        (TxKind.PRESTAMO, Direction.IN, False, False),
        (TxKind.PRESTAMO, Direction.OUT, False, False),
    ],
)
def test_clasificacion(kind, direction, expense, income):
    assert counts_as_expense(kind, direction) is expense
    assert counts_as_income(kind, direction) is income


def test_sentidos_permitidos():
    assert allowed_directions(TxKind.GASTO) == {Direction.OUT}
    assert allowed_directions(TxKind.INGRESO) == {Direction.IN}
    assert allowed_directions(TxKind.PRESTAMO) == {Direction.IN, Direction.OUT}
    with pytest.raises(ValueError):
        allowed_directions("otro")


def test_transferencias():
    assert is_transfer(TxKind.RETIRO_EFECTIVO)
    assert not is_transfer(TxKind.PRESTAMO)


def test_monto_con_signo():
    assert signed_amount(Decimal("5"), Direction.IN) == Decimal("5")
    assert signed_amount(Decimal("5"), Direction.OUT) == Decimal("-5")
    with pytest.raises(ValueError):
        signed_amount(Decimal("5"), "x")
