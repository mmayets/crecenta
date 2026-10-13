"""Ventas sin conexión: el lote se valida con el formulario de venta y no duplica."""

import json
import uuid
from decimal import Decimal

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.accounts.tests.factories import UserFactory
from apps.business.models import Product, Sale
from apps.ledger.models import Account, Transaction
from apps.workspaces.models import Membership

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture
def vendedora(business_ws):
    persona = UserFactory(email="carla@example.com")
    Membership.objects.create(user=persona, workspace=business_ws, role="vendedor")
    Product.objects.create(workspace=business_ws, name="Refresco", price=D("75"), unit_cost=D("50"))
    return persona


def item(ws, qty="2", **kw):
    fields = {
        "date": "2026-10-13",
        "payment": "contado",
        "account": str(Account.objects.get(workspace=ws, name="Efectivo").pk),
        "producto_1": str(Product.objects.get(name="Refresco").pk),
        "cantidad_1": qty,
        "note": "Sin señal",
        **kw,
    }
    return {"client_uuid": str(uuid.uuid4()), "form": fields}


def enviar(client, ws, items):
    url = reverse("business:sales_sync", kwargs={"ws": ws.pk})
    return client.post(url, json.dumps({"items": items}), content_type="application/json")


def test_sincroniza_sin_duplicar(client, business_ws, vendedora):
    client.force_login(vendedora)
    a, b = item(business_ws), item(business_ws, "3")
    malo = item(business_ws, "0")
    response = enviar(client, business_ws, [a, b, malo, "x", {"client_uuid": "y"}])
    estados = [r["estado"] for r in response.json()["resultados"]]
    assert estados == ["creado", "creado", "error", "error", "error"]
    assert "cantidad_1" in response.json()["resultados"][2]["errores"]
    assert Sale.objects.count() == 2
    venta = Sale.objects.get(client_uuid=a["client_uuid"])
    assert venta.created_by == vendedora and venta.total == D("150.00")
    assert Transaction.objects.get(sale=venta).source == "offline" and venta.note == "Sin señal"
    again = enviar(client, business_ws, [a])  # reintento
    assert again.json()["resultados"][0]["estado"] == "existente"
    assert Sale.objects.count() == 2


def test_errores_de_servicio_y_formato(client, business_ws, vendedora):
    client.force_login(vendedora)
    insumo = Product.objects.create(
        workspace=business_ws, name="Hielo", price=0, unit_cost=0, is_supply=True,
        tracks_inventory=True,
    )  # fmt: skip
    r = enviar(client, business_ws, [item(business_ws, producto_1=str(insumo.pk))])
    assert r.json()["resultados"][0]["estado"] == "error"  # el insumo no está entre las opciones
    url = reverse("business:sales_sync", kwargs={"ws": business_ws.pk})
    assert client.post(url, "{", content_type="application/json").status_code == 400
    assert client.post(url, "[]", content_type="application/json").status_code == 400
    muchos = [item(business_ws) for _ in range(51)]
    assert enviar(client, business_ws, muchos).status_code == 400


def test_error_del_servicio(client, business_ws, vendedora, monkeypatch):
    from django.core.exceptions import ValidationError

    def falla(*a, **k):
        raise ValidationError("No se pudo")

    monkeypatch.setattr("apps.business.sync_views.register_sale", falla)
    client.force_login(vendedora)
    r = enviar(client, business_ws, [item(business_ws)])
    assert r.json()["resultados"][0] == {
        "client_uuid": r.json()["resultados"][0]["client_uuid"],
        "estado": "error",
        "errores": {"": ["No se pudo"]},
    }


@override_settings(SYNC_RATE_LIMITS=[(1, 60)])
def test_limite_de_envios(client, business_ws, vendedora):
    client.force_login(vendedora)
    assert enviar(client, business_ws, []).status_code == 200
    assert enviar(client, business_ws, []).status_code == 429


def test_espacio_personal_no_tiene_ventas(client, user, personal_ws):
    client.force_login(user)
    assert enviar(client, personal_ws, []).status_code == 404
