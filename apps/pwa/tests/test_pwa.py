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


def test_boton_instalar_arriba_en_todas_las_pantallas(client, user):
    """Oculto de entrada: app.js lo muestra en el teléfono si se puede instalar."""
    for html in (
        client.get(reverse("home")).content.decode(),  # portada pública
        client.get(reverse("account_login")).content.decode(),
    ):
        bar = html.index("data-install ")
        assert html.index("<body") < bar < html.index('id="contenido"')
        assert 'data-testid="instalar-app"' in html
    client.force_login(user)
    html = client.get(reverse("asistente:first_space"), follow=True).content.decode()
    assert "data-install " in html  # también en el paso a paso de Sophia


def test_publicada_bajo_un_prefijo(client, settings):
    """En producción la app vive en /crecenta/: manifest, service worker y registro lo respetan."""
    from django.urls import set_script_prefix

    settings.FORCE_SCRIPT_NAME = "/crecenta"
    settings.STATIC_URL = "/crecenta/static/"
    # El servidor (WSGIHandler/ASGIHandler) fija el prefijo en cada petición a partir de
    # FORCE_SCRIPT_NAME; el cliente de pruebas no lo hace, así que se fija aquí.
    set_script_prefix("/crecenta/")
    try:
        manifest = client.get("/manifest.webmanifest").json()
        assert manifest["start_url"] == "/crecenta/?origen=pwa"
        assert manifest["scope"] == "/crecenta/"
        response = client.get("/sw.js")
        assert response["Service-Worker-Allowed"] == "/crecenta/"
        body = response.content.decode()
        assert 'const STATIC_PREFIX = "/crecenta/static/"' in body
        assert '"/crecenta/static/css/app.css"' in body and 'const HOME_URL = "/crecenta/"' in body
        html = client.get("/").content.decode()
        assert 'content="/crecenta/sw.js" data-scope="/crecenta/"' in html
        assert 'href="/crecenta/static/css/app.css"' in html
    finally:
        set_script_prefix("/")
