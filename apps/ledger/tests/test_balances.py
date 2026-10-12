from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.ledger.choices import Direction, TxKind, TxStatus
from apps.ledger.models import Category
from apps.ledger.services.balances import (
    account_balance,
    balances_by_account,
    expense_total,
    income_total,
    spent_by_category,
    total_balance,
)
from apps.ledger.services.recording import (
    TxData,
    create_account,
    record_transaction,
    record_transfer,
)

pytestmark = pytest.mark.django_db
D = Decimal
OCT1, OCT31 = date(2026, 10, 1), date(2026, 10, 31)


@pytest.fixture
def setup(personal_ws, user):
    cats = {c.name: c for c in Category.objects.for_workspace(personal_ws)}
    banco = create_account(personal_ws, "Banco", "banco", "10000")
    efectivo = personal_ws_efectivo(personal_ws)
    return personal_ws, user, cats, banco, efectivo


def personal_ws_efectivo(ws):
    from apps.ledger.models import Account

    return Account.objects.for_workspace(ws).get(name="Efectivo")


def add(ws, user, account, amount, kind, direction, on=date(2026, 10, 5), category=None, **kw):
    return record_transaction(
        ws,
        user,
        TxData(
            account=account,
            date=on,
            amount=D(amount),
            direction=direction,
            kind=kind,
            category=category,
            **kw,
        ),
    )


def test_saldo_inicial_y_movimientos(setup):
    ws, user, cats, banco, _ = setup
    add(ws, user, banco, "50000", TxKind.INGRESO, Direction.IN, category=cats["Salario"])
    add(ws, user, banco, "18000", TxKind.GASTO, Direction.OUT, category=cats["Alquiler o hipoteca"])
    assert account_balance(banco) == D("42000.00")
    assert total_balance(ws) == D("42000.00")


def test_pendiente_de_revision_no_mueve_saldo(setup):
    ws, user, cats, banco, _ = setup
    add(ws, user, banco, "500", TxKind.GASTO, Direction.OUT, status=TxStatus.PENDIENTE_REVISION)
    assert account_balance(banco) == D("10000")
    assert spent_by_category(ws, OCT1, OCT31) == {}


def test_saldo_a_una_fecha(setup):
    ws, user, cats, banco, _ = setup
    add(ws, user, banco, "1000", TxKind.GASTO, Direction.OUT, on=date(2026, 10, 20))
    assert account_balance(banco, as_of=date(2026, 10, 19)) == D("10000")
    assert account_balance(banco, as_of=date(2026, 10, 20)) == D("9000")
    assert total_balance(ws, as_of=date(2026, 10, 19)) == D("10000")


def test_transferencia_y_retiro_no_son_gasto(setup):
    ws, user, cats, banco, efectivo = setup
    out_leg, in_leg = record_transfer(
        ws,
        user,
        from_account=banco,
        to_account=efectivo,
        amount="3000",
        on=OCT1,
        kind=TxKind.RETIRO_EFECTIVO,
    )
    record_transfer(ws, user, from_account=efectivo, to_account=banco, amount="500", on=OCT1)
    assert out_leg.transfer_pair == in_leg and in_leg.transfer_pair == out_leg
    balances = balances_by_account(ws)
    assert balances[banco.pk] == D("7500")
    assert balances[efectivo.pk] == D("2500")
    assert total_balance(ws) == D("10000")  # el total no cambia
    assert expense_total(ws, OCT1, OCT31) == D("0")
    assert income_total(ws, OCT1, OCT31) == D("0")


def test_ahorro_por_transferencia_no_es_gasto(setup):
    ws, user, cats, banco, _ = setup
    ahorro = create_account(ws, "Ahorro", "banco")
    record_transfer(
        ws,
        user,
        from_account=banco,
        to_account=ahorro,
        amount="7000",
        on=OCT1,
        category=cats["Ahorro"],
    )
    assert expense_total(ws, OCT1, OCT31) == D("0")
    assert total_balance(ws) == D("10000")


def test_prestamo_aumenta_efectivo_pero_no_es_ingreso(setup):
    ws, user, cats, banco, _ = setup
    add(ws, user, banco, "20000", TxKind.PRESTAMO, Direction.IN)
    assert total_balance(ws) == D("30000")
    assert income_total(ws, OCT1, OCT31) == D("0")


def test_gasto_por_categoria(setup):
    ws, user, cats, banco, efectivo = setup
    add(ws, user, banco, "1200.50", TxKind.GASTO, Direction.OUT, category=cats["Alimentación"])
    add(ws, user, efectivo, "799.50", TxKind.GASTO, Direction.OUT, category=cats["Alimentación"])
    add(
        ws,
        user,
        banco,
        "3000",
        TxKind.PAGO_DEUDA,
        Direction.OUT,
        category=cats["Préstamos y deudas"],
    )
    add(ws, user, banco, "100", TxKind.GASTO, Direction.OUT)  # sin categoría
    add(ws, user, banco, "999", TxKind.GASTO, Direction.OUT, on=date(2026, 11, 1))  # fuera
    spent = spent_by_category(ws, OCT1, OCT31)
    assert spent == {
        cats["Alimentación"].pk: D("2000.00"),
        cats["Préstamos y deudas"].pk: D("3000.00"),
        None: D("100.00"),
    }
    assert expense_total(ws, OCT1, OCT31) == D("5100.00")


def test_tarjeta_de_credito_resta_al_total(setup):
    ws, user, cats, banco, _ = setup
    tarjeta = create_account(ws, "Tarjeta", "tarjeta")
    add(ws, user, tarjeta, "2500", TxKind.GASTO, Direction.OUT, category=cats["Ropa"])
    assert account_balance(tarjeta) == D("-2500")
    assert total_balance(ws) == D("7500")


def test_aislamiento_de_saldos(setup, other_ws, other_user):
    ws, *_ = setup
    otra = create_account(other_ws, "Banco B", "banco", "99999")
    assert otra.pk not in balances_by_account(ws)
    assert total_balance(ws) == D("10000")


def test_registro_rechaza_transferencias_y_errores(setup):
    ws, user, cats, banco, efectivo = setup
    with pytest.raises(ValidationError):
        add(ws, user, banco, "10", TxKind.TRANSFERENCIA_INTERNA, Direction.OUT)
    with pytest.raises(ValidationError):
        record_transfer(ws, user, from_account=banco, to_account=banco, amount="10", on=OCT1)
    with pytest.raises(ValidationError):
        record_transfer(
            ws,
            user,
            from_account=banco,
            to_account=efectivo,
            amount="10",
            on=OCT1,
            kind=TxKind.GASTO,
        )
