import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.workspaces.models import Membership, Workspace
from apps.workspaces.services.workspaces import (
    create_workspace,
    create_workspaces_for_usage,
    default_workspace,
    user_workspaces,
)

pytestmark = pytest.mark.django_db


def test_crear_espacio_crea_membresia(user):
    ws = create_workspace(user, "personal")
    assert ws.name == "Mis finanzas"
    assert ws.currency == "DOP"
    assert ws.is_personal and not ws.is_business
    assert Membership.objects.get(workspace=ws).user == user
    assert str(ws) == "Mis finanzas"


def test_moneda_usd(user):
    assert create_workspace(user, "business", currency="USD").currency == "USD"


def test_moneda_invalida(user):
    with pytest.raises(ValidationError):
        create_workspace(user, "personal", currency="EUR")


def test_solo_un_espacio_personal(user):
    create_workspace(user, "personal")
    with pytest.raises((IntegrityError, ValidationError)):
        create_workspace(user, "personal")


def test_varios_negocios(user):
    create_workspace(user, "business", name="Uno")
    create_workspace(user, "business", name="Dos")
    assert Workspace.objects.filter(owner=user, kind="business").count() == 2


@pytest.mark.parametrize(
    ("usage", "kinds"),
    [("persona", ["personal"]), ("negocio", ["business"]), ("ambos", ["personal", "business"])],
)
def test_uso(user, usage, kinds):
    created = create_workspaces_for_usage(user, usage)
    assert sorted(w.kind for w in created) == sorted(kinds)


def test_uso_es_idempotente(user):
    create_workspaces_for_usage(user, "ambos", business_name="Dulces Ariel")
    assert create_workspaces_for_usage(user, "ambos") == []
    assert Workspace.objects.filter(owner=user).count() == 2
    assert Workspace.objects.get(owner=user, kind="business").name == "Dulces Ariel"


def test_uso_invalido(user):
    with pytest.raises(ValueError):
        create_workspaces_for_usage(user, "otro")  # type: ignore[arg-type]


def test_espacios_del_usuario_no_incluye_ajenos(user, personal_ws, other_ws):
    assert user_workspaces(user) == [personal_ws]


def test_espacio_por_defecto(user, other_ws):
    assert default_workspace(user) is None
    negocio = create_workspace(user, "business")
    personal = create_workspace(user, "personal")
    assert default_workspace(user) == personal  # el personal primero
    assert default_workspace(user, negocio.pk) == negocio
    assert default_workspace(user, other_ws.pk) == personal  # ajeno → se ignora
    assert default_workspace(user, "no-es-uuid") == personal
