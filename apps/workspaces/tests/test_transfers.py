import datetime
import uuid
from decimal import Decimal
from unittest import mock

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.urls import reverse

from apps.ledger.choices import TxKind
from apps.ledger.models import Account, Category, Transaction
from apps.ledger.services.balances import income_total
from apps.ledger.services.classification import counts_as_expense, counts_as_income
from apps.workspaces.models import Membership, WorkspaceTransfer
from apps.workspaces.services import transfers as svc
from apps.workspaces.services.transfers import delete_transfer, transfer_between, transfer_for
from apps.workspaces.services.workspaces import create_workspace

D = Decimal
HOY = datetime.date(2026, 10, 13)
RETIRO, APORTE = WorkspaceTransfer.Kind.RETIRO_PROPIETARIO, WorkspaceTransfer.Kind.APORTE


def caja(ws):
    return Account.objects.get(workspace=ws, name="Efectivo")


def retiro(user, negocio, persona, amount="5000", **kw):
    return transfer_between(
        user, negocio, persona, amount, HOY, RETIRO, caja(negocio), caja(persona), **kw
    )


def test_retiro_crea_movimientos_espejo(user, personal_ws, business_ws):
    # Espacio personal "antiguo": todavía sin la categoría nueva.
    Category.objects.filter(workspace=personal_ws, name="Retiros de mi negocio").delete()
    t, created = retiro(user, business_ws, personal_ws, note="Quincena")
    assert created and t.amount == D("5000")
    out, inn = t.out_tx, t.in_tx
    assert out.workspace == business_ws and out.kind == TxKind.RETIRO_PROPIETARIO
    assert out.direction == "out" and out.category.name == "Retiros del propietario"
    assert out.description == "Retiro hacia Mis finanzas · Quincena"
    assert inn.workspace == personal_ws and inn.kind == TxKind.INGRESO and inn.direction == "in"
    assert inn.category.name == "Retiros de mi negocio" and inn.category.is_system
    # Para la persona es ingreso; para el negocio no es gasto.
    assert counts_as_income(inn.kind, inn.direction)
    assert not counts_as_expense(out.kind, out.direction)
    assert income_total(personal_ws, HOY, HOY) == D("5000")
    assert transfer_for(out) == t == transfer_for(inn)


def test_aporte_es_neutro_en_ambos_lados(user, personal_ws, business_ws):
    t, _ = transfer_between(
        user, personal_ws, business_ws, "10000", HOY, APORTE, caja(personal_ws), caja(business_ws)
    )
    out, inn = t.out_tx, t.in_tx
    assert out.kind == inn.kind == TxKind.APORTE_PROPIETARIO and out.category is None
    assert inn.category.name == "Aportes del propietario"
    for tx in (out, inn):
        assert not counts_as_expense(tx.kind, tx.direction)
        assert not counts_as_income(tx.kind, tx.direction)


def test_reenvio_no_duplica(user, personal_ws, business_ws):
    uid = uuid.uuid4()
    a, c1 = retiro(user, business_ws, personal_ws, client_uuid=uid)
    b, c2 = retiro(user, business_ws, personal_ws, client_uuid=uid)
    assert c1 and not c2 and a.pk == b.pk and Transaction.objects.count() == 2


def test_carrera_devuelve_la_existente(user, personal_ws, business_ws):
    uid = uuid.uuid4()
    existing, _ = retiro(user, business_ws, personal_ws, client_uuid=uid)
    with mock.patch.object(svc, "_create", side_effect=IntegrityError("x")):
        calls = {"n": 0}
        real = WorkspaceTransfer.objects.filter

        def fake(*a, **k):
            calls["n"] += 1
            qs = real(*a, **k)
            return qs.none() if calls["n"] == 1 else qs

        with mock.patch.object(WorkspaceTransfer.objects, "filter", side_effect=fake):
            found, created = retiro(user, business_ws, personal_ws, client_uuid=uid)
        assert not created and found.pk == existing.pk
        with pytest.raises(IntegrityError):
            retiro(user, business_ws, personal_ws, client_uuid=uuid.uuid4())


def test_solo_entre_espacios_propios(user, other_user, personal_ws, business_ws, other_ws):
    with pytest.raises(ValidationError):
        transfer_between(
            user, business_ws, other_ws, "1", HOY, RETIRO, caja(business_ws), caja(other_ws)
        )
    # Ser dueño en el registro sin membresía de propietario tampoco basta.
    Membership.objects.filter(user=user, workspace=personal_ws).delete()
    with pytest.raises(ValidationError):
        retiro(user, business_ws, personal_ws)


def test_validaciones(user, personal_ws, business_ws):
    with pytest.raises(ValidationError) as exc:  # retiro en sentido contrario
        transfer_between(
            user, personal_ws, business_ws, "1", HOY, RETIRO, caja(personal_ws), caja(business_ws)
        )
    assert "kind" in exc.value.message_dict
    with pytest.raises(ValidationError) as exc:  # aporte en sentido contrario
        transfer_between(
            user, business_ws, personal_ws, "1", HOY, APORTE, caja(business_ws), caja(personal_ws)
        )
    assert "kind" in exc.value.message_dict
    with pytest.raises(ValidationError) as exc:
        transfer_between(
            user, business_ws, personal_ws, "1", HOY, "otro", caja(business_ws), caja(personal_ws)
        )
    assert "kind" in exc.value.message_dict
    with pytest.raises(ValidationError) as exc:  # cuentas cruzadas
        transfer_between(
            user, business_ws, personal_ws, "1", HOY, RETIRO, caja(personal_ws), caja(business_ws)
        )
    assert {"from_account", "to_account"} <= set(exc.value.message_dict)
    with pytest.raises(ValidationError) as exc:
        retiro(user, business_ws, personal_ws, amount="0")
    assert "amount" in exc.value.message_dict
    usd = create_workspace(user, "business", name="Tienda USD", currency="USD")
    with pytest.raises(ValidationError) as exc:  # monedas distintas sin tasa
        retiro(user, usd, personal_ws)
    assert "exchange_rate" in exc.value.message_dict


def test_monedas_distintas_con_tasa(user, personal_ws):
    from apps.workspaces.services.transfers import convert

    usd = create_workspace(user, "business", name="Tienda USD", currency="USD")
    t, _ = retiro(user, usd, personal_ws, amount="100", exchange_rate=D("60.50"))
    assert t.amount == D("100") and t.in_amount == D("6050.00")
    assert t.exchange_rate == D("60.5000")
    assert t.out_tx.amount == D("100.00") and t.in_tx.amount == D("6050.00")
    assert "(tasa 60.5)" in t.in_tx.description
    aporte, _ = transfer_between(
        user, personal_ws, usd, "6050", HOY, APORTE, caja(personal_ws), caja(usd),
        exchange_rate=D("60.50"),
    )  # fmt: skip
    assert aporte.in_tx.amount == D("100.00")
    assert convert(D("5"), "DOP", "DOP", None) == D("5")
    with pytest.raises(ValidationError):
        convert(D("5"), "USD", "DOP", D("0"))
    with pytest.raises(ValidationError):
        convert(D("5"), "USD", "EUR", D("1"))
    same, _ = retiro(user, create_workspace(user, "business", name="Otro"), personal_ws,
                     exchange_rate=D("60"))  # fmt: skip
    assert same.exchange_rate is None and same.in_amount == same.amount


def test_borrar_transferencia_borra_ambos_movimientos(user, other_user, personal_ws, business_ws):
    t, _ = retiro(user, business_ws, personal_ws)
    with pytest.raises(ValidationError):
        delete_transfer(other_user, t)
    delete_transfer(user, t)
    assert not WorkspaceTransfer.objects.exists() and not Transaction.objects.exists()


def test_borrar_desde_movimientos_borra_el_espejo(client, user, personal_ws, business_ws):
    t, _ = retiro(user, business_ws, personal_ws)
    client.force_login(user)
    url = reverse("ledger:delete", kwargs={"ws": personal_ws.pk, "tx_id": t.in_tx.pk})
    client.post(url)
    assert not Transaction.objects.exists() and not WorkspaceTransfer.objects.exists()
