"""Permisos por rol en un negocio compartido (docs/fase4.md §2).

Recorre todas las rutas de /e/<uuid:ws>/: el vendedor solo entra a las de vender; el administrador
a todas menos las del propietario. Una ruta nueva queda cerrada para el vendedor por defecto.
"""

import pytest

from apps.accounts.tests.factories import UserFactory
from apps.business.models import Product
from apps.workspaces.models import Membership
from tests.test_aislamiento import ROUTES, build_url

VENDEDOR_PUEDE = {
    "espacio:dashboard",
    "espacio:settings",
    "business:sales",
    "business:sale_new",
    "business:sale_detail",
    "business:receivables",
    "business:collect",
    "business:inventory",
}
SOLO_PROPIETARIO = {
    "espacio:team",
    "espacio:member_role",
    "espacio:member_remove",
    "espacio:invitation_revoke",
    "business:owner",
    "business:owner_check",
}
# Rutas sin objeto en la URL: si el rol puede, la página abre.
SIN_OBJETO = {"espacio:dashboard", "espacio:settings", "business:sales", "business:sale_new",
              "business:receivables", "business:inventory"}  # fmt: skip


def miembro(business_ws, role):
    Product.objects.get_or_create(
        workspace=business_ws, name="Bizcocho", defaults={"price": 500, "unit_cost": 300}
    )
    persona = UserFactory(email=f"{role}@example.com")
    Membership.objects.create(user=persona, workspace=business_ws, role=role)
    return persona


def nombre(namespace, pattern):
    return f"{namespace}:{pattern.name}"


@pytest.mark.django_db
@pytest.mark.parametrize(("namespace", "pattern"), ROUTES, ids=lambda v: getattr(v, "name", v))
def test_vendedor_solo_entra_a_vender(client, business_ws, namespace, pattern):
    client.force_login(miembro(business_ws, "vendedor"))
    response = client.get(build_url(namespace, pattern, business_ws.pk))
    ruta = nombre(namespace, pattern)
    if ruta not in VENDEDOR_PUEDE:
        assert response.status_code == 404, ruta
        assert client.post(build_url(namespace, pattern, business_ws.pk)).status_code == 404
    elif ruta in SIN_OBJETO:
        assert response.status_code == 200, ruta


@pytest.mark.django_db
@pytest.mark.parametrize(("namespace", "pattern"), ROUTES, ids=lambda v: getattr(v, "name", v))
def test_administrador_todo_menos_propietario(client, business_ws, namespace, pattern):
    client.force_login(miembro(business_ws, "admin"))
    response = client.get(build_url(namespace, pattern, business_ws.pk))
    ruta = nombre(namespace, pattern)
    if ruta in SOLO_PROPIETARIO:
        assert response.status_code == 404, ruta
    elif ruta in SIN_OBJETO:
        assert response.status_code == 200, ruta


def test_rutas_declaradas_existen():
    nombres = {nombre(ns, p) for ns, p in ROUTES}
    assert nombres >= VENDEDOR_PUEDE and nombres >= SOLO_PROPIETARIO


@pytest.mark.django_db
def test_sin_membresia_no_hay_permisos():
    from apps.workspaces.permissions import FINANZAS, can, perms_for

    assert perms_for(None) == frozenset() and not can("desconocido", FINANZAS)
