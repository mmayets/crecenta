import json
import uuid

import pytest
from django.urls import reverse

from apps.ledger.models import Account, Transaction

pytestmark = pytest.mark.django_db


def url(ws):
    return reverse("ledger:sync", kwargs={"ws": ws.pk})


def item(ws):
    return {
        "client_uuid": str(uuid.uuid4()),
        "account_id": str(Account.objects.for_workspace(ws).get(name="Efectivo").pk),
        "date": "2026-10-05",
        "amount": "125.50",
        "kind": "gasto",
    }


def post(client, ws, body):
    return client.post(url(ws), data=json.dumps(body), content_type="application/json")


def test_sincroniza_sin_duplicar(client, user, personal_ws):
    client.force_login(user)
    data = item(personal_ws)
    first = post(client, personal_ws, {"items": [data]})
    second = post(client, personal_ws, {"items": [data]})
    assert first.status_code == second.status_code == 200
    assert first.json()["resultados"][0]["estado"] == "creado"
    assert second.json()["resultados"][0]["estado"] == "existente"
    assert Transaction.objects.for_workspace(personal_ws).count() == 1


def test_requiere_post(client, user, personal_ws):
    client.force_login(user)
    assert client.get(url(personal_ws)).status_code == 405


@pytest.mark.parametrize("body", [b"{no json", b"[]", b'{"items": {}}', b"\xff"])
def test_cuerpo_invalido(client, user, personal_ws, body):
    client.force_login(user)
    response = client.post(url(personal_ws), data=body, content_type="application/json")
    assert response.status_code == 400


def test_lote_demasiado_grande(client, user, personal_ws):
    client.force_login(user)
    assert post(client, personal_ws, {"items": [{}] * 101}).status_code == 400


def test_exige_csrf(user, personal_ws):
    from django.test import Client

    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    assert post(client, personal_ws, {"items": [item(personal_ws)]}).status_code == 403


def test_limite_de_sincronizacion(client, user, personal_ws, settings):
    settings.SYNC_RATE_LIMITS = [(1, 60)]
    client.force_login(user)
    assert post(client, personal_ws, {"items": []}).status_code == 200
    assert post(client, personal_ws, {"items": []}).status_code == 429


def test_avisos_ignoran_montos_absurdos(client, user, personal_ws):
    from django.urls import reverse

    client.force_login(user)
    url = reverse("ledger:warnings", kwargs={"ws": personal_ws.pk})
    for value in ("1e999999", "NaN", "Infinity", "-1e9999"):
        assert client.post(url, {"amount": value}).status_code == 200
