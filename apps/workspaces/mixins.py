"""Resolución del espacio activo y control de acceso.

Toda vista de dominio vive bajo `/e/<uuid:ws>/` y usa `WorkspaceRequiredMixin` (o el decorador
`workspace_required`). Un espacio ajeno o inexistente responde 404 para no revelar su existencia.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ValidationError
from django.db.models import Model, QuerySet
from django.http import Http404, HttpRequest, HttpResponse

from .models import Workspace

SESSION_KEY = "workspace_id"


def resolve_workspace(request: HttpRequest, workspace_id: Any) -> Workspace:
    try:
        workspace = Workspace.objects.for_user(request.user).get(pk=workspace_id)
    except (Workspace.DoesNotExist, ValueError, ValidationError) as exc:
        raise Http404("Espacio no encontrado") from exc
    request.workspace = workspace  # type: ignore[attr-defined]
    request.session[SESSION_KEY] = str(workspace.pk)
    return workspace


class WorkspaceRequiredMixin(LoginRequiredMixin):
    """Exige sesión y membresía en el espacio de la URL; expone `self.workspace`."""

    workspace: Workspace
    workspace_kind: str | None = None  # restringe a "personal" o "business" si se define

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.workspace = resolve_workspace(request, kwargs.pop("ws"))
        if self.workspace_kind and self.workspace.kind != self.workspace_kind:
            raise Http404("Esta sección no existe para este tipo de espacio")
        return super().dispatch(request, *args, **kwargs)

    def scoped(self, model: type[Model]) -> QuerySet:
        """Queryset del modelo filtrado por el espacio activo."""
        return model.objects.for_workspace(self.workspace)  # type: ignore[attr-defined]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)  # type: ignore[misc]
        context["workspace"] = self.workspace
        return context


def workspace_required(
    view: Callable[..., HttpResponse] | None = None, *, kind: str | None = None
) -> Any:
    """Decorador para vistas-función: inyecta `workspace` como primer argumento tras request."""

    def decorator(func: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
        @wraps(func)
        def wrapper(request: HttpRequest, *args: Any, ws: Any, **kwargs: Any) -> HttpResponse:
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            workspace = resolve_workspace(request, ws)
            if kind and workspace.kind != kind:
                raise Http404("Esta sección no existe para este tipo de espacio")
            return func(request, workspace, *args, **kwargs)

        return wrapper

    return decorator(view) if view else decorator
