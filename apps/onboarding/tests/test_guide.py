from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.accounts.tests.factories import UserFactory
from apps.ai.providers import FakeProvider
from apps.alerts.models import Alert
from apps.business.models import Product, Receivable
from apps.onboarding.services import guide
from apps.onboarding.services.steps import get_state
from apps.workspaces.models import Membership

pytestmark = pytest.mark.django_db

TODAY = date(2026, 10, 13)


def keys(workspace, user, role="owner"):
    return [s.key for s in guide.suggestions(workspace, user, role, TODAY)]


def url(workspace, name):
    return reverse(f"onboarding:{name}", kwargs={"ws": workspace.pk})


# ---------------------------------------------------------------- recomendaciones


def test_espacio_personal_nuevo_pide_completar_y_registrar(user, personal_ws):
    found = keys(personal_ws, user)
    assert found[0] == "perfil"
    assert {"registrar", "ia", "negocio"} <= set(found)
    assert "plan" not in found  # sin perfil no hay plan que proponer


def test_datos_por_confirmar_y_alerta_urgente_van_primero(user, personal_ws, business_ws):
    state = get_state(personal_ws)
    state.pending_extraction = {"ingresos": []}
    state.save()
    Alert.objects.create(
        workspace=personal_ws,
        code="x",
        severity=Alert.Severity.ALTA,
        title="Te pasaste en ocio",
        message="…",
        period_start=TODAY.replace(day=1),
    )
    user.set_ai_consent(True)
    found = guide.suggestions(personal_ws, user, "owner", TODAY)
    assert found[0].key == "alerta" and found[0].tone == guide.URGENT
    assert found[0].title == "Te pasaste en ocio"
    assert found[1].key == "confirmar"
    # Ya tiene negocio y dio el consentimiento: esas dos no aparecen.
    assert not {"ia", "negocio"} & {s.key for s in found}


def test_negocio_recomienda_productos_cobros_vencidos_y_ventas(user, business_ws):
    assert "productos" in keys(business_ws, user)
    Product.objects.create(workspace=business_ws, name="Bizcocho", price=500, unit_cost=300)
    Receivable.objects.create(
        workspace=business_ws,
        concept="Pedido del hotel",
        amount=Decimal("3000"),
        due_date=TODAY - timedelta(days=2),
    )
    found = guide.suggestions(business_ws, user, "owner", TODAY)
    by_key = {s.key: s for s in found}
    assert "productos" not in by_key
    assert by_key["cobrar"].tone == guide.URGENT and "Pedido del hotel" in by_key["cobrar"].text
    assert by_key["vender"].url == reverse("business:sale_new", kwargs={"ws": business_ws.pk})
    assert found[0].tone == guide.URGENT


def test_vendedor_solo_ve_lo_que_puede_hacer(user, business_ws):
    seller = UserFactory(email="vendedor@example.com")
    Membership.objects.create(user=seller, workspace=business_ws, role="vendedor")
    assert set(keys(business_ws, seller, "vendedor")) <= {"vender", "cobrar", "inventario"}
    catalog = guide.destinations(business_ws, "vendedor")
    assert {"vender", "por_cobrar", "inventario"} <= set(catalog)
    assert not {"reportes", "productos", "retiros", "gasto", "plan"} & set(catalog)


def test_catalogo_segun_tipo_de_espacio(personal_ws, business_ws):
    personal = set(guide.destinations(personal_ws, "owner"))
    business = set(guide.destinations(business_ws, "owner"))
    assert "transferir" in personal and "vender" not in personal
    assert {"vender", "retiros", "equipo"} <= business and "transferir" not in business
    assert "retiros" not in guide.destinations(business_ws, "admin")


# ---------------------------------------------------------------- panel


def test_panel_muestra_recomendaciones_consejo_y_tira(client, user, personal_ws):
    client.force_login(user)
    response = client.get(url(personal_ws, "guide"), {"vista": "ledger:movements"})
    html = response.content.decode()
    assert response.status_code == 200
    assert 'data-recomendacion="perfil"' in html
    assert guide.PAGE_TIPS["ledger:movements"] in html
    assert 'id="asistente-tira" hx-swap-oob="innerHTML"' in html and 'data-testid="tira"' in html
    assert "Completa tu perfil" in html


def test_panel_no_recomienda_la_pantalla_actual(client, user, personal_ws):
    client.force_login(user)
    here = reverse("onboarding:index", kwargs={"ws": personal_ws.pk})
    response = client.get(
        url(personal_ws, "guide"), headers={"HX-Current-URL": f"http://testserver{here}"}
    )
    assert 'data-recomendacion="perfil"' not in response.content.decode()


def test_las_paginas_del_espacio_cargan_el_asistente(client, user, personal_ws):
    client.force_login(user)
    html = client.get(reverse("espacio:dashboard", kwargs={"ws": personal_ws.pk})).content.decode()
    assert f'hx-get="{url(personal_ws, "guide")}?vista=espacio:dashboard"' in html
    assert 'data-testid="asistente"' in html
    # Fuera de un espacio no hay asistente flotante.
    assert (
        'data-testid="asistente"' not in client.get(reverse("accounts:settings")).content.decode()
    )


# ---------------------------------------------------------------- preguntas


def ask(client, workspace, question):
    return client.post(url(workspace, "ask"), {"pregunta": question, "vista": "espacio:dashboard"})


def test_pregunta_sin_ia_responde_con_reglas(client, user, personal_ws):
    client.force_login(user)
    html = ask(client, personal_ws, "¿Cómo paso dinero de una cuenta a otra?").content.decode()
    assert "Transferir entre cuentas" in html
    assert reverse("ledger:transfer", kwargs={"ws": personal_ws.pk}) in html
    assert not FakeProvider.calls

    html = ask(client, personal_ws, "xyz").content.decode()
    assert "No estoy seguro" in html


def test_pregunta_con_ia_usa_el_catalogo(client, user, business_ws):
    user.set_ai_consent(True)
    client.force_login(user)
    FakeProvider.queue({"mensaje": "Ve a Reportes y descarga el 607.", "destinos": ["reportes"]})
    html = ask(client, business_ws, "¿dónde saco el 607?").content.decode()
    assert "Ve a Reportes y descarga el 607." in html
    assert reverse("business:reports", kwargs={"ws": business_ws.pk}) in html
    sent = FakeProvider.calls[0]["user"]
    assert '"clave": "reportes"' in sent and "¿dónde saco el 607?" in sent


def test_la_ia_no_puede_inventar_destinos(client, user, personal_ws):
    user.set_ai_consent(True)
    client.force_login(user)
    bad = {"mensaje": "Entra aquí.", "destinos": ["https://malo.example", "retiros"]}
    FakeProvider.queue(bad, bad)
    html = ask(client, personal_ws, "¿cómo veo mi plan?").content.decode()
    # Rechazada dos veces → respuesta por reglas, solo con enlaces propios.
    assert "malo.example" not in html and "Entra aquí." not in html
    assert reverse("planning:index", kwargs={"ws": personal_ws.pk}) in html


def test_pregunta_vacia_no_responde(client, user, personal_ws):
    client.force_login(user)
    assert ask(client, personal_ws, "  ").content == b""
