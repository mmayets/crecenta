"""Creación y selección de espacios financieros."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounts.models import User
from apps.workspaces.models import Membership, Workspace

Usage = Literal["persona", "negocio", "ambos"]

DEFAULT_NAMES = {Workspace.Kind.PERSONAL: "Mis finanzas", Workspace.Kind.BUSINESS: "Mi negocio"}


@transaction.atomic
def create_workspace(
    user: User, kind: str, name: str | None = None, currency: str | None = None
) -> Workspace:
    """Crea un espacio con el usuario como propietario y miembro."""
    workspace = Workspace(owner=user, kind=kind, name=name or DEFAULT_NAMES[Workspace.Kind(kind)])
    if currency:
        workspace.currency = currency
    workspace.full_clean()
    workspace.save()
    Membership.objects.create(user=user, workspace=workspace, role=Membership.Role.OWNER)
    return workspace


@transaction.atomic
def create_workspaces_for_usage(
    user: User, usage: Usage, currency: str | None = None, business_name: str | None = None
) -> list[Workspace]:
    """Paso 0 del onboarding. Idempotente: no duplica el espacio personal ni el de negocio."""
    if usage not in ("persona", "negocio", "ambos"):
        raise ValueError(f"Uso no válido: {usage}")
    owned = Workspace.objects.filter(owner=user)
    created: list[Workspace] = []
    if usage in ("persona", "ambos") and not owned.filter(kind=Workspace.Kind.PERSONAL).exists():
        created.append(create_workspace(user, Workspace.Kind.PERSONAL, currency=currency))
    if usage in ("negocio", "ambos") and not owned.filter(kind=Workspace.Kind.BUSINESS).exists():
        created.append(
            create_workspace(user, Workspace.Kind.BUSINESS, name=business_name, currency=currency)
        )
    return created


def user_workspaces(user: User) -> list[Workspace]:
    return list(Workspace.objects.for_user(user).personal_first())


def default_workspace(user: User, preferred_id: str | UUID | None = None) -> Workspace | None:
    """Último espacio usado si sigue siendo accesible; si no, el personal; si no, el primero."""
    workspaces = Workspace.objects.for_user(user)
    if preferred_id:
        try:
            preferred: Workspace = workspaces.get(pk=preferred_id)
            return preferred
        except (Workspace.DoesNotExist, ValueError, ValidationError):
            pass
    fallback: Workspace | None = workspaces.personal_first().first()
    return fallback
