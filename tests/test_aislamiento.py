"""Aislamiento entre usuarios: ninguna ruta de dominio es accesible desde un espacio ajeno.

Recorre automáticamente todas las rutas montadas bajo /e/<uuid:ws>/ (config.workspace_urls), de
modo que cada vista nueva queda cubierta sin escribir un test adicional.
"""

import uuid

import pytest
from django.urls import URLPattern, URLResolver, reverse

from config import workspace_urls

CONVERTER_SAMPLES = {
    "UUIDConverter": lambda: uuid.uuid4(),
    "IntConverter": lambda: 1,
    "StringConverter": lambda: "x",
    "SlugConverter": lambda: "x",
    "PathConverter": lambda: "x",
}


def collect(patterns, namespace=None):
    for entry in patterns:
        if isinstance(entry, URLResolver):
            ns = entry.namespace or namespace
            yield from collect(entry.url_patterns, ns)
        elif isinstance(entry, URLPattern):
            yield namespace, entry


ROUTES = list(collect(workspace_urls.urlpatterns))


def test_todas_las_rutas_tienen_nombre():
    assert ROUTES
    for namespace, pattern in ROUTES:
        assert pattern.name, f"Ruta sin nombre: {pattern.pattern}"
        assert namespace, f"Ruta sin namespace: {pattern.pattern}"


def build_url(namespace, pattern, ws_id):
    kwargs = {"ws": ws_id}
    for name, converter in pattern.pattern.converters.items():
        kwargs[name] = CONVERTER_SAMPLES[type(converter).__name__]()
    return reverse(f"{namespace}:{pattern.name}", kwargs=kwargs)


@pytest.mark.django_db
@pytest.mark.parametrize(("namespace", "pattern"), ROUTES, ids=lambda v: getattr(v, "name", v))
@pytest.mark.parametrize("method", ["get", "post"])
def test_espacio_ajeno_responde_404(client, user, other_ws, namespace, pattern, method):
    client.force_login(user)
    response = getattr(client, method)(build_url(namespace, pattern, other_ws.pk))
    assert response.status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize(("namespace", "pattern"), ROUTES, ids=lambda v: getattr(v, "name", v))
def test_espacio_inexistente_responde_404(client, user, namespace, pattern):
    client.force_login(user)
    assert client.get(build_url(namespace, pattern, uuid.uuid4())).status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize(("namespace", "pattern"), ROUTES, ids=lambda v: getattr(v, "name", v))
def test_anonimo_no_accede(client, other_ws, namespace, pattern):
    response = client.get(build_url(namespace, pattern, other_ws.pk))
    assert response.status_code in (302, 404)
    if response.status_code == 302:
        assert reverse("account_login") in response["Location"]
