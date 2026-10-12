import uuid
from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.ai.providers import FakeProvider
from apps.ai.schemas import QuickEntry
from apps.ledger.models import Account, Category, Transaction
from apps.ledger.services.quick_entry import draft_from_entry
from apps.ledger.services.recording import create_account

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture
def logged(client, user):
    client.force_login(user)
    return client


def url(name, ws, **kw):
    return reverse(f"ledger:{name}", kwargs={"ws": ws.pk, **kw})


def cat(ws, name):
    return Category.objects.for_workspace(ws).get(name=name)


def efectivo(ws):
    return Account.objects.for_workspace(ws).get(name="Efectivo")


def quick(ws, **kw):
    data = {
        "kind": "gasto",
        "amount": "350",
        "category": cat(ws, "Alimentación").pk,
        "account": efectivo(ws).pk,
        "date": "2026-10-05",
        "description": "Colmado",
        "client_uuid": str(uuid.uuid4()),
        "source": "manual",
    }
    data.update(kw)
    return data


def test_registro_rapido_y_doble_envio(logged, personal_ws):
    page = logged.get(url("new", personal_ws)).content.decode()
    assert "Registrar movimiento" in page and 'inputmode="decimal"' in page
    data = quick(personal_ws)
    assert logged.post(url("new", personal_ws), data)["Location"] == url("movements", personal_ws)
    response = logged.post(url("new", personal_ws), data, follow=True)  # doble toque
    assert "ya estaba registrado" in response.content.decode()
    tx = Transaction.objects.for_workspace(personal_ws).get()
    assert (tx.amount, tx.source, tx.kind) == (D("350.00"), "manual", "gasto")


def test_registro_invalido(logged, personal_ws):
    response = logged.post(url("new", personal_ws), quick(personal_ws, kind="ingreso"))
    assert response.status_code == 400  # ingreso con categoría de gasto
    assert not Transaction.objects.exists()
    assert logged.post(url("new", personal_ws), quick(personal_ws, amount="0")).status_code == 400
    page = logged.get(url("new", personal_ws), {"tipo": "ingreso"}).content.decode()
    assert 'value="ingreso" checked' in page or 'value="ingreso"\n' in page or "checked" in page


def test_lista_por_mes_y_filtro(logged, personal_ws):
    logged.post(url("new", personal_ws), quick(personal_ws))
    logged.post(
        url("new", personal_ws),
        quick(
            personal_ws,
            kind="ingreso",
            amount="1000",
            description="Quincena",
            category=cat(personal_ws, "Salario").pk,
        ),
    )
    html = logged.get(url("movements", personal_ws), {"mes": "2026-10"}).content.decode()
    assert "RD$1,000.00" in html and "RD$350.00" in html and "Colmado" in html
    html = logged.get(
        url("movements", personal_ws),
        {"mes": "2026-10", "categoria": cat(personal_ws, "Salario").pk},
    ).content.decode()
    assert "Colmado" not in html
    assert (
        "No hay movimientos"
        in logged.get(url("movements", personal_ws), {"mes": "2026-09"}).content.decode()
    )
    assert (
        logged.get(url("movements", personal_ws), {"mes": "basura", "categoria": "x"}).status_code
        == 200
    )


def test_texto_libre_crea_borrador_no_movimiento(logged, user, personal_ws):
    user.set_ai_consent(True)
    FakeProvider.queue(
        QuickEntry(
            tipo="gasto",
            monto=D("350"),
            categoria="colmado",
            descripcion="Colmado",
            confianza={"monto": 0.95, "fecha": 0.3},
        )
    )
    html = logged.post(
        url("from_text", personal_ws), {"texto": "gasté 350 en el colmado", "via": "voz"}
    ).content.decode()
    assert "Esto es lo que entendimos" in html
    assert 'value="350"' in html or 'value="350.00"' in html
    assert 'class="dudoso"' in html  # fecha con baja confianza
    assert 'name="source" value="voz"' in html
    assert not Transaction.objects.exists()


def test_texto_libre_sin_ia_o_transferencia(logged, user, personal_ws):
    response = logged.post(url("from_text", personal_ws), {"texto": "gasté 350"}, follow=True)
    assert "Puedes registrarlo con el formulario" in response.content.decode()
    response = logged.post(url("from_text", personal_ws), {"texto": ""}, follow=True)
    assert "Escribe el movimiento" in response.content.decode()
    user.set_ai_consent(True)
    FakeProvider.queue(QuickEntry(tipo="retiro_efectivo", monto=D("2000")))
    response = logged.post(url("from_text", personal_ws), {"texto": "saqué 2000 del cajero"})
    assert response["Location"] == url("transfer", personal_ws)


def test_borrador_desde_la_ia(personal_ws):
    create_account(personal_ws, "Banco Popular", "banco")
    draft = draft_from_entry(
        personal_ws,
        QuickEntry(
            tipo="ingreso",
            monto=D("25000"),
            categoria="quincena",
            cuenta="popular",
            fecha=date(2026, 10, 15),
            confianza={"monto": 1, "fecha": 1, "categoria": 1, "cuenta": 1},
        ),
        date(2026, 10, 16),
    )
    assert draft.category.name == "Salario" and draft.account.name == "Banco Popular"
    assert draft.doubtful == frozenset()
    sin_datos = draft_from_entry(
        personal_ws, QuickEntry(tipo="gasto", monto=D("5")), date(2026, 10, 16)
    )
    assert {"category", "account", "date"} <= sin_datos.doubtful
    assert sin_datos.account == efectivo(personal_ws) and sin_datos.date == date(2026, 10, 16)
    assert sin_datos.initial()["category"] is None


def test_transferencia_y_ahorro(logged, personal_ws):
    banco = create_account(personal_ws, "Banco", "banco", "10000")
    data = {
        "kind": "retiro_efectivo",
        "from_account": banco.pk,
        "to_account": efectivo(personal_ws).pk,
        "amount": "3000",
        "date": "2026-10-05",
        "client_uuid": str(uuid.uuid4()),
    }
    assert logged.post(url("transfer", personal_ws), data).status_code == 302
    assert Transaction.objects.for_workspace(personal_ws).count() == 2
    ahorro = create_account(personal_ws, "Ahorro", "banco", is_savings=True)
    data = {
        **data,
        "kind": "transferencia_interna",
        "to_account": ahorro.pk,
        "is_saving": "on",
        "client_uuid": str(uuid.uuid4()),
    }
    logged.post(url("transfer", personal_ws), data)
    assert (
        Transaction.objects.for_workspace(personal_ws).filter(category__name="Ahorro").count() == 2
    )
    same = {**data, "to_account": banco.pk, "client_uuid": str(uuid.uuid4())}
    assert logged.post(url("transfer", personal_ws), same).status_code == 400
    assert "No cuenta como gasto" in logged.get(url("transfer", personal_ws)).content.decode()


def test_transferencia_con_error_de_servicio(logged, personal_ws):
    banco = create_account(personal_ws, "Banco", "banco")
    banco.is_archived = True
    banco.save()
    data = {
        "kind": "transferencia_interna",
        "from_account": efectivo(personal_ws).pk,
        "to_account": banco.pk,
        "amount": "1",
        "date": "2026-10-05",
        "client_uuid": str(uuid.uuid4()),
    }
    assert logged.post(url("transfer", personal_ws), data).status_code == 400


def test_eliminar_movimiento_y_transferencia(logged, personal_ws):
    banco = create_account(personal_ws, "Banco", "banco", "10000")
    logged.post(
        url("transfer", personal_ws),
        {
            "kind": "retiro_efectivo",
            "from_account": banco.pk,
            "to_account": efectivo(personal_ws).pk,
            "amount": "3000",
            "date": "2026-10-05",
            "client_uuid": str(uuid.uuid4()),
        },
    )
    tx = Transaction.objects.for_workspace(personal_ws).first()
    logged.post(url("delete", personal_ws, tx_id=tx.pk))
    assert not Transaction.objects.exists()
    assert logged.post(url("delete", personal_ws, tx_id=uuid.uuid4())).status_code == 404


def test_avisos_previos(logged, personal_ws):
    from apps.personal.tests.data import load_caso_50000

    load_caso_50000(personal_ws)
    response = logged.post(
        url("warnings", personal_ws),
        {"amount": "5000", "category": str(cat(personal_ws, "Alimentación").pk)},
    )
    assert "dinero comprometido" in response.content.decode()
    assert (
        logged.post(url("warnings", personal_ws), {"amount": "x", "category": "y"}).content.strip()
        == b""
    )
    assert (
        logged.post(
            url("warnings", personal_ws), {"amount": "5", "kind": "ingreso"}
        ).content.strip()
        == b""
    )


def test_ajustes_de_cuentas(logged, personal_ws):
    html = logged.get(url("accounts", personal_ws)).content.decode()
    assert "No guardamos números de cuenta" in html and "Efectivo" in html
    data = {"name": "Visa", "type": "tarjeta", "opening_balance": "-1500"}
    assert logged.post(url("accounts", personal_ws), data).status_code == 302
    visa = Account.objects.for_workspace(personal_ws).get(name="Visa")
    assert visa.currency == "DOP"
    logged.post(url("account_edit", personal_ws, account_id=visa.pk), {**data, "name": "Visa Oro"})
    visa.refresh_from_db()
    assert visa.name == "Visa Oro"
    logged.post(url("account_edit", personal_ws, account_id=visa.pk), {"archivar": "1"})
    visa.refresh_from_db()
    assert visa.is_archived
    assert "archivada" in logged.get(url("accounts", personal_ws)).content.decode()
    assert logged.get(url("account_edit", personal_ws, account_id=uuid.uuid4())).status_code == 404
    assert logged.post(url("accounts", personal_ws), {"name": ""}).status_code == 200


def test_ajustes_de_categorias(logged, personal_ws, business_ws):
    ropa = cat(personal_ws, "Ropa")
    logged.post(
        url("category_edit", personal_ws, category_id=ropa.pk),
        {"name": "Ropa", "group": "discrecional"},
    )
    ropa.refresh_from_db()
    assert ropa.group == "discrecional"
    logged.post(url("categories", personal_ws), {"name": "Mascotas", "group": "esencial_variable"})
    assert (
        Category.objects.for_workspace(personal_ws)
        .filter(name="Mascotas", is_system=False)
        .exists()
    )
    logged.post(url("category_edit", personal_ws, category_id=ropa.pk), {"archivar": "1"})
    ropa.refresh_from_db()
    assert ropa.is_archived
    html = logged.get(url("categories", business_ws)).content.decode()
    assert "Costos variables" in html and "Esenciales variables" not in html
    assert (
        logged.get(url("category_edit", personal_ws, category_id=uuid.uuid4())).status_code == 404
    )
    assert (
        logged.post(url("categories", personal_ws), {"name": "", "group": "x"}).status_code == 200
    )
