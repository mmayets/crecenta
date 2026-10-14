from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.ai.providers import FakeProvider, ProviderError
from apps.ledger.models import Account, Category, Transaction
from apps.ledger.services import centia
from apps.ledger.services.recording import create_account

pytestmark = pytest.mark.django_db
D = Decimal
TODAY = date(2026, 10, 13)
CONTEXT = {
    "hoy": TODAY.isoformat(),
    "tipos": {"gasto": "Gasto", "ingreso": "Ingreso", "pago_deuda": "Cuota"},
    "categorias": ["Alimentación", "Salario", "Electricidad"],
    "cuentas": ["Efectivo", "Banco Popular"],
}


@pytest.fixture
def logged(client, user):
    client.force_login(user)
    return client


def url(name, ws):
    return reverse(f"ledger:{name}", kwargs={"ws": ws.pk})


def say(client, ws, text):
    return client.post(url("centia", ws), {"texto": text})


def state_of(client, ws):
    return client.session[f"centia:{ws.pk}"]


# ---------------------------------------------------------------- reglas (sin IA)


@pytest.mark.parametrize(
    ("text", "pending", "expected"),
    [
        (
            "gasté 350 en el colmado ayer",
            ["tipo", "monto"],
            {"tipo": "gasto", "monto": D("350"), "fecha": date(2026, 10, 12),
             "categoria": "Alimentación"},
        ),
        ("me pagaron 50 mil de sueldo", ["tipo", "monto"],
         {"tipo": "ingreso", "monto": D("50000"), "categoria": "Salario"}),
        ("pagué 2,500.50 de luz con el banco popular", ["monto"],
         {"tipo": "gasto", "monto": D("2500.50"), "categoria": "Electricidad",
          "cuenta": "Banco Popular"}),
        ("Cuota", ["tipo"], {"tipo": "pago_deuda"}),
        ("saqué del cajero 2000", ["tipo", "monto"],
         {"tipo": "retiro_efectivo", "monto": D("2000")}),
        ("fue el día 5", ["cuenta"], {}),  # un número suelto no cambia un monto ya anotado
        ("eran 450", ["cuenta"], {"monto": D("450")}),
        ("Efectivo", ["cuenta"], {"cuenta": "Efectivo"}),
    ],
)  # fmt: skip
def test_reglas_entienden_frases_simples(text, pending, expected):
    turn = centia.interpret_by_rules(text, pending, CONTEXT)
    found = {k: v for k, v in turn.model_dump().items() if v}
    assert found == expected


# ---------------------------------------------------------------- chat


def test_la_pagina_muestra_a_centia(logged, personal_ws):
    html = logged.get(url("new", personal_ws)).content.decode()
    assert 'id="centia"' in html and "Soy CentIA" in html
    assert "Sin el uso de IA activado" in html


def test_sin_ia_arma_el_movimiento_y_solo_guarda_al_confirmar(logged, user, personal_ws):
    say(logged, personal_ws, "gasté 350 en el colmado ayer")
    state = state_of(logged, personal_ws)
    comida = Category.objects.for_workspace(personal_ws).get(name="Alimentación")
    efectivo = Account.objects.for_workspace(personal_ws).get(name="Efectivo")
    draft = dict(state["draft"])
    assert draft.pop("date")  # «ayer» respecto al día en que corre el test
    assert draft == {
        "kind": "gasto",
        "amount": "350.00",
        "account_id": str(efectivo.pk),  # única cuenta: no hace falta preguntar
        "category_id": str(comida.pk),
        "description": "gasté 350 en el colmado ayer",
    }
    assert state["messages"][-1]["texto"].startswith("Listo: gasto de RD$350.00 en Alimentación")
    # Conversar no guarda nada.
    assert not Transaction.objects.for_workspace(personal_ws).exists()
    assert not FakeProvider.calls

    page = logged.get(url("new", personal_ws)).content.decode()
    assert 'data-testid="centia-propuesta"' in page and 'data-testid="centia-guardar"' in page

    response = logged.post(
        url("centia_save", personal_ws), {"client_uuid": "0d0f6f0e-8f0a-4b61-9a43-1b1c9d2f3a10"}
    )
    assert response["Location"] == url("movements", personal_ws)
    tx = Transaction.objects.for_workspace(personal_ws).get()
    assert (tx.amount, tx.kind, tx.category, tx.account) == (D("350.00"), "gasto", comida, efectivo)
    # La conversación empieza de cero tras guardar.
    assert f"centia:{personal_ws.pk}" not in logged.session


def test_pregunta_lo_que_falta_con_opciones(logged, personal_ws):
    create_account(personal_ws, "Banco Popular", "banco")
    say(logged, personal_ws, "compré unos zapatos")
    state = state_of(logged, personal_ws)
    assert state["draft"]["kind"] == "gasto" and "amount" not in state["draft"]
    assert state["messages"][-1]["texto"] == "Anoté: gasto. ¿De cuánto fue?"

    say(logged, personal_ws, "1,800")
    html = logged.get(url("new", personal_ws)).content.decode()
    assert "¿Con qué cuenta fue?" in html
    assert 'value="Banco Popular"' in html and 'value="Efectivo"' in html

    say(logged, personal_ws, "Banco Popular")
    assert centia.missing(personal_ws, state_of(logged, personal_ws)["draft"]) == ["categoria"]
    say(logged, personal_ws, "Sin categoría")
    state = state_of(logged, personal_ws)
    assert state["draft"]["category_skipped"] is True
    assert state["messages"][-1]["texto"].startswith(
        "Listo: gasto de RD$1,800.00 con Banco Popular"
    )


def test_corregir_despues_del_resumen(logged, personal_ws):
    say(logged, personal_ws, "gasté 350 en el colmado")
    say(logged, personal_ws, "eran 450")
    assert state_of(logged, personal_ws)["draft"]["amount"] == "450.00"


def test_con_ia_usa_lo_que_entendio_y_empareja_nombres(logged, user, personal_ws):
    user.set_ai_consent(True)
    create_account(personal_ws, "Banco Popular", "banco")
    FakeProvider.queue(
        {
            "mensaje": "Anotado el pago de la luz. ¿Con qué cuenta lo pagaste?",
            "tipo": "gasto",
            "monto": "2500",
            "categoria": "luz",
            "descripcion": "Pago de la luz",
        }
    )
    say(logged, personal_ws, "pagué dos mil quinientos de luz")
    state = state_of(logged, personal_ws)
    luz = Category.objects.for_workspace(personal_ws).get(name="Electricidad")
    assert state["draft"]["category_id"] == str(luz.pk)
    assert state["draft"]["description"] == "Pago de la luz"
    assert state["messages"][-1]["texto"].startswith("Anotado el pago de la luz")
    sent = FakeProvider.calls[0]["user"]
    assert "Banco Popular" in sent and "pagué dos mil quinientos de luz" in sent

    # Una cuenta que no existe no se inventa: sigue faltando.
    FakeProvider.queue({"mensaje": "Listo, guardado.", "cuenta": "Banco Imaginario"})
    say(logged, personal_ws, "con el banco imaginario")
    state = state_of(logged, personal_ws)
    assert "account_id" not in state["draft"]
    assert not Transaction.objects.for_workspace(personal_ws).exists()


def test_ia_caida_degrada_a_reglas(logged, user, personal_ws):
    user.set_ai_consent(True)
    FakeProvider.queue(ProviderError("sin red"), ProviderError("sin red"))
    say(logged, personal_ws, "gasté 350 en el colmado")
    assert state_of(logged, personal_ws)["draft"]["amount"] == "350.00"


def test_transferencia_se_deriva_a_su_pantalla(logged, personal_ws):
    say(logged, personal_ws, "saqué del cajero 2000")
    state = state_of(logged, personal_ws)
    assert state["draft"] == {}
    assert state["messages"][-1]["enlaces"][0]["url"] == url("transfer", personal_ws)


def test_guardar_sin_propuesta_no_guarda(logged, personal_ws):
    say(logged, personal_ws, "compré algo")
    logged.post(url("centia_save", personal_ws), {"client_uuid": ""})
    assert not Transaction.objects.for_workspace(personal_ws).exists()
    assert "No pude guardarlo" in state_of(logged, personal_ws)["messages"][-1]["texto"]


def test_editar_abre_el_formulario_con_el_borrador(logged, personal_ws):
    say(logged, personal_ws, "gasté 350 en el colmado")
    html = logged.get(url("new", personal_ws) + "?centia=1").content.decode()
    assert 'value="350.00"' in html and "Esto es lo que entendimos" in html


def test_reiniciar_y_htmx(logged, personal_ws):
    response = logged.post(
        url("centia", personal_ws), {"texto": "gasté 350"}, headers={"HX-Request": "true"}
    )
    html = response.content.decode()
    assert html.lstrip().startswith('<section id="centia"') and "<html" not in html
    logged.post(url("centia_restart", personal_ws))
    assert f"centia:{personal_ws.pk}" not in logged.session


def test_cada_espacio_tiene_su_conversacion(logged, personal_ws, business_ws):
    say(logged, personal_ws, "gasté 777 en el colmado")
    assert f"centia:{business_ws.pk}" not in logged.session
    html = logged.get(url("new", business_ws)).content.decode()
    assert "gasté 777" not in html and "al suplidor" in html
