from datetime import date

import pytest
from django.urls import reverse

from apps.alerts.models import Alert, AlertRule
from apps.alerts.services.evaluate import evaluate_workspace
from apps.ledger.services.recording import create_account
from apps.personal.tests.data import load_caso_50000

pytestmark = pytest.mark.django_db


@pytest.fixture
def con_alertas(client, user, personal_ws):
    load_caso_50000(personal_ws)
    create_account(personal_ws, "Banco", "banco", "1000")
    evaluate_workspace(personal_ws, date(2026, 10, 13))
    client.force_login(user)
    return personal_ws


def url(name, ws, **kw):
    return reverse(f"alerts:{name}", kwargs={"ws": ws.pk, **kw})


def test_lista_y_marca_como_vistas(client, con_alertas):
    html = client.get(url("index", con_alertas)).content.decode()
    assert "No te alcanza para un pago próximo" in html
    assert "Datos usados" in html and "Nueva" in html
    assert not Alert.objects.for_workspace(con_alertas).filter(status="nueva").exists()


def test_descartar_y_resolver(client, con_alertas):
    a, b = Alert.objects.for_workspace(con_alertas)[:2]
    client.post(url("dismiss", con_alertas, alert_id=a.pk))
    client.post(url("resolve", con_alertas, alert_id=b.pk))
    a.refresh_from_db()
    b.refresh_from_db()
    assert a.status == "descartada" and b.status == "resuelta" and b.resolved_at
    html = client.get(url("index", con_alertas)).content.decode()
    assert "Anteriores" in html
    assert (
        client.post(
            url("dismiss", con_alertas, alert_id="00000000-0000-0000-0000-000000000000")
        ).status_code
        == 404
    )


def test_configurar_reglas(client, con_alertas):
    form = client.get(url("rules", con_alertas)).content.decode()
    assert "Pago próximo sin dinero suficiente" in form
    data = {
        "categoria_80__enabled": "on",
        "categoria_80__umbral_pct": "70",
        "riesgo_fin_periodo__dias_minimos": "5",
        "pago_sin_cobertura__enabled": "on",
        "pago_sin_cobertura__dias_antes": "7",
        "meta_en_riesgo__dias_gracia": "3",
        "buen_desempeno__avance_minimo_pct": "50",
    }
    assert client.post(url("rules", con_alertas), data).status_code == 302
    rule = AlertRule.objects.for_workspace(con_alertas).get(code="categoria_80")
    assert rule.params == {"umbral_pct": 70}
    assert not AlertRule.objects.for_workspace(con_alertas).get(code="meta_en_riesgo").enabled
    assert (
        client.post(
            url("rules", con_alertas), {**data, "categoria_80__umbral_pct": "0"}
        ).status_code
        == 200
    )


def test_sin_alertas(client, user, personal_ws):
    client.force_login(user)
    assert "No tienes alertas pendientes" in client.get(url("index", personal_ws)).content.decode()
