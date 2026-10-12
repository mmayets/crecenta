import uuid
from decimal import Decimal
from unittest import mock

import pytest
from django.core.exceptions import ValidationError

from apps.ledger.choices import Direction, TxKind
from apps.ledger.models import Account, Category, Transaction
from apps.ledger.services import sync
from apps.ledger.services.recording import create_account
from apps.ledger.services.sync import MAX_BATCH, parse_item, sync_batch, upsert_from_client

pytestmark = pytest.mark.django_db


def efectivo(ws):
    return Account.objects.for_workspace(ws).get(name="Efectivo")


def payload(ws, **overrides):
    data = {
        "client_uuid": str(uuid.uuid4()),
        "account_id": str(efectivo(ws).pk),
        "date": "2026-10-05",
        "amount": "350.00",
        "kind": "gasto",
        "category_id": str(Category.objects.for_workspace(ws).get(name="Alimentación").pk),
        "description": "Colmado",
    }
    data.update(overrides)
    return data


def test_mismo_client_uuid_dos_veces_crea_un_solo_movimiento(personal_ws, user):
    raw = payload(personal_ws)
    first = upsert_from_client(personal_ws, user, parse_item(personal_ws, raw))
    second = upsert_from_client(personal_ws, user, parse_item(personal_ws, raw))
    assert first.created and not second.created
    assert first.transaction.pk == second.transaction.pk
    assert Transaction.objects.for_workspace(personal_ws).count() == 1
    tx = first.transaction
    assert (tx.direction, tx.source, tx.amount) == (Direction.OUT, "offline", Decimal("350.00"))


def test_gana_la_primera_escritura(personal_ws, user):
    raw = payload(personal_ws)
    upsert_from_client(personal_ws, user, parse_item(personal_ws, raw))
    raw["amount"] = "999"
    result = upsert_from_client(personal_ws, user, parse_item(personal_ws, raw))
    assert result.transaction.amount == Decimal("350.00")


def test_mismo_client_uuid_en_otro_espacio_es_independiente(
    personal_ws, other_ws, user, other_user
):
    shared = str(uuid.uuid4())
    upsert_from_client(
        personal_ws, user, parse_item(personal_ws, payload(personal_ws, client_uuid=shared))
    )
    result = upsert_from_client(
        other_ws, other_user, parse_item(other_ws, payload(other_ws, client_uuid=shared))
    )
    assert result.created


def test_carrera_concurrente_devuelve_existente(personal_ws, user):
    raw = payload(personal_ws)
    item = parse_item(personal_ws, raw)
    upsert_from_client(personal_ws, user, item)
    real = sync._existing
    calls = {"n": 0}

    def first_miss(ws, cu):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(ws, cu)

    with mock.patch.object(sync, "_existing", side_effect=first_miss):
        result = upsert_from_client(personal_ws, user, item)
    assert not result.created
    assert Transaction.objects.for_workspace(personal_ws).count() == 1


def test_integrity_error_sin_existente_se_propaga(personal_ws, user):
    from django.db import IntegrityError

    item = parse_item(personal_ws, payload(personal_ws))
    with (
        mock.patch.object(sync, "record_transaction", side_effect=IntegrityError("x")),
        pytest.raises(IntegrityError),
    ):
        upsert_from_client(personal_ws, user, item)


def test_transferencia_offline_idempotente(personal_ws, user):
    banco = create_account(personal_ws, "Banco", "banco", "5000")
    raw = payload(
        personal_ws,
        account_id=str(banco.pk),
        to_account_id=str(efectivo(personal_ws).pk),
        kind="retiro_efectivo",
        category_id="",
    )
    for _ in range(3):
        upsert_from_client(personal_ws, user, parse_item(personal_ws, raw))
    assert Transaction.objects.for_workspace(personal_ws).count() == 2


def test_prestamo_requiere_sentido(personal_ws):
    with pytest.raises(ValidationError) as exc:
        parse_item(personal_ws, payload(personal_ws, kind="prestamo", category_id=""))
    assert "direction" in exc.value.message_dict
    item = parse_item(
        personal_ws, payload(personal_ws, kind="prestamo", direction="in", category_id="")
    )
    assert item.direction == "in"


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"client_uuid": "no"}, "client_uuid"),
        ({"account_id": str(uuid.uuid4())}, "account_id"),
        ({"account_id": "basura"}, "account_id"),
        ({"date": "05/10/2026"}, "date"),
        ({"amount": "abc"}, "amount"),
        ({"amount": "0"}, "amount"),
        ({"amount": "-5"}, "amount"),
        ({"kind": "regalo"}, "kind"),
        ({"category_id": str(uuid.uuid4())}, "category_id"),
        ({"kind": "transferencia_interna", "category_id": ""}, "to_account_id"),
        ({"source": "comprobante"}, "source"),
    ],
)
def test_validaciones(personal_ws, overrides, field):
    with pytest.raises(ValidationError) as exc:
        parse_item(personal_ws, payload(personal_ws, **overrides))
    assert field in exc.value.message_dict


def test_no_acepta_cuenta_ni_categoria_de_otro_espacio(personal_ws, other_ws):
    raw = payload(
        personal_ws,
        account_id=str(efectivo(other_ws).pk),
        category_id=str(Category.objects.for_workspace(other_ws).first().pk),
    )
    with pytest.raises(ValidationError) as exc:
        parse_item(personal_ws, raw)
    assert {"account_id", "category_id"} <= set(exc.value.message_dict)


def test_cuenta_archivada_no_se_acepta(personal_ws):
    Account.objects.for_workspace(personal_ws).update(is_archived=True)
    with pytest.raises(ValidationError):
        parse_item(personal_ws, payload(personal_ws))


def test_lote_mixto(personal_ws, user):
    ok = payload(personal_ws)
    salario = Category.objects.for_workspace(personal_ws).get(name="Salario")
    results = sync_batch(
        personal_ws,
        user,
        [
            ok,
            ok,
            payload(personal_ws, amount="x"),
            payload(personal_ws, category_id=str(salario.pk)),  # gasto con categoría de ingreso
            "no-es-objeto",
            payload(personal_ws, kind=TxKind.INGRESO, category_id=str(salario.pk)),
        ],
    )
    assert [r["estado"] for r in results] == [
        "creado",
        "existente",
        "error",
        "error",
        "error",
        "creado",
    ]
    assert results[0]["id"] == results[1]["id"]
    assert "amount" in results[2]["errores"]
    assert "category" in results[3]["errores"]
    assert Transaction.objects.for_workspace(personal_ws).count() == 2


def test_lote_demasiado_grande(personal_ws, user):
    with pytest.raises(ValidationError):
        sync_batch(personal_ws, user, [{}] * (MAX_BATCH + 1))
