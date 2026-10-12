"""Querysets que garantizan el aislamiento por espacio financiero."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import models

if TYPE_CHECKING:
    from apps.accounts.models import User

    from .models import Workspace


class WorkspaceQuerySet(models.QuerySet):
    def for_user(self, user: User) -> WorkspaceQuerySet:
        """Espacios de los que el usuario es miembro (ninguno si no está autenticado)."""
        if not user.is_authenticated:
            return self.none()
        return self.filter(memberships__user=user).distinct()

    def personal_first(self) -> WorkspaceQuerySet:
        """El espacio personal primero; luego los negocios por antigüedad."""
        return self.annotate(
            _orden=models.Case(
                models.When(kind="personal", then=models.Value(0)),
                default=models.Value(1),
                output_field=models.IntegerField(),
            )
        ).order_by("_orden", "created_at")


class WorkspaceScopedQuerySet(models.QuerySet):
    """Base de todo modelo de dominio: obliga a filtrar por espacio de forma explícita."""

    def for_workspace(self, workspace: Workspace) -> WorkspaceScopedQuerySet:
        if workspace is None or workspace._state.adding:
            raise ValueError("Se requiere un espacio para consultar datos de dominio")
        return self.filter(workspace=workspace)
