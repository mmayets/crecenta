import json

import pytest
from django.contrib.staticfiles import finders
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_manifest_instalable(client):
    response = client.get("/manifest.webmanifest")
    assert response["Content-Type"] == "application/manifest+json"
    data = json.loads(response.content)
    assert (data["display"], data["lang"], data["start_url"], data["scope"]) == (
        "standalone",
        "es-DO",
        "/?origen=pwa",
        "/",
    )
    sizes = {i["sizes"] for i in data["icons"]}
    assert {"192x192", "512x512"} <= sizes
    assert any(i.get("purpose") == "maskable" for i in data["icons"])
    for icon in data["icons"]:
        assert finders.find(icon["src"].removeprefix("/static/")), icon["src"]
    assert data["shortcuts"][0]["url"] == reverse("pwa:quick_entry")


def test_service_worker(client, settings):
    response = client.get("/sw.js")
    assert response["Content-Type"].startswith("application/javascript")
    assert response["Service-Worker-Allowed"] == "/"
    assert "no-cache" in response["Cache-Control"] or "max-age=0" in response["Cache-Control"]
    body = response.content.decode()
    assert 'importScripts("/static/js/offline-queue.js")' in body
    assert '"/sin-conexion/"' in body and '"/static/css/app.css"' in body
    assert "sync-movimientos" in body
    precache = json.loads(body.split("const PRECACHE = ")[1].split(";\n")[0])
    for url in precache:
        if url.startswith("/static/"):
            assert finders.find(url.removeprefix("/static/")), url
    version = body.split('const VERSION = "')[1][:12]
    settings.APP_VERSION = "2"
    assert client.get("/sw.js").content.decode().split('const VERSION = "')[1][:12] != version


def test_paginas_sin_conexion_no_requieren_sesion(client):
    html = client.get(reverse("pwa:offline")).content.decode()
    assert "Estás sin conexión" in html and "data-pending-count" in html
    html = client.get(reverse("pwa:offline_saved")).content.decode()
    assert "Lo guardamos en tu teléfono" in html


def test_atajo_registrar(client, user, personal_ws):
    assert client.get(reverse("pwa:quick_entry")).status_code == 302  # login
    client.force_login(user)
    assert client.get(reverse("pwa:quick_entry"))["Location"] == reverse(
        "ledger:new", kwargs={"ws": personal_ws.pk}
    )


def test_atajo_sin_espacios(client, user):
    client.force_login(user)
    assert client.get(reverse("pwa:quick_entry"))["Location"] == reverse("workspaces:usage")


def test_base_enlaza_manifest_e_iconos(client, user, personal_ws):
    client.force_login(user)
    html = client.get(reverse("ledger:new", kwargs={"ws": personal_ws.pk})).content.decode()
    assert 'rel="manifest" href="/manifest.webmanifest"' in html
    assert "apple-touch-icon" in html and "offline-queue.js" in html
    assert 'id="estado-red"' in html
    assert 'name="client_uuid"' in html
