"""Chat de Sophia en «Registrar movimiento» (ver `services/sophia.py`).

La conversación vive en la sesión, una por espacio; nada llega a la base hasta «Guardar».
"""

from __future__ import annotations

import uuid
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.ratelimit import hit
from apps.workspaces.mixins import workspace_required
from apps.workspaces.models import Workspace

from .services import sophia


def _key(workspace: Workspace) -> str:
    return f"sophia:{workspace.pk}"


def get_state(request: HttpRequest, workspace: Workspace) -> dict[str, Any]:
    state = request.session.get(_key(workspace))
    if not state:
        state = sophia.new_state(workspace, request.user)  # type: ignore[arg-type]
    return state


def _store(request: HttpRequest, workspace: Workspace, state: dict[str, Any] | None) -> None:
    if state is None:
        request.session.pop(_key(workspace), None)
    else:
        request.session[_key(workspace)] = state


def sophia_context(
    request: HttpRequest, workspace: Workspace, state: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Lo que necesita `ledger/_sophia.html` (también lo usa la vista del formulario)."""
    state = state or get_state(request, workspace)
    return {
        "workspace": workspace,
        "sophia": state,
        "sophia_replies": sophia.quick_replies(workspace, state),
        "sophia_proposal": sophia.proposal(workspace, state),
        "sophia_ai_off": not request.user.ai_consent,  # type: ignore[union-attr]
        "sophia_uuid": uuid.uuid4(),
    }


def _respond(request: HttpRequest, workspace: Workspace, state: dict[str, Any]) -> HttpResponse:
    if request.headers.get("HX-Request"):
        return render(request, "ledger/_sophia.html", sophia_context(request, workspace, state))
    return redirect("ledger:sophia", ws=workspace.pk)


@workspace_required
@require_http_methods(["GET", "POST"])
def message(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    """GET: pantalla con Sophia sola, que guía todo el registro. POST: un turno del chat."""
    state = get_state(request, workspace)
    if request.method == "GET":
        return render(request, "ledger/sophia.html", sophia_context(request, workspace, state))
    if hit(f"sophia:{request.user.pk}", settings.SYNC_RATE_LIMITS):
        sophia.take_turn(
            state,
            workspace,
            request.user,  # type: ignore[arg-type]
            request.POST.get("texto", ""),
            timezone.localdate(),
        )
        _store(request, workspace, state)
    return _respond(request, workspace, state)


@workspace_required
@require_POST
def save(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    from .views import _save_quick  # misma ruta de guardado que el formulario

    state = get_state(request, workspace)
    form = sophia.build_form(state, workspace, request.POST.get("client_uuid", ""))
    if (
        sophia.proposal(workspace, state)
        and form.is_valid()
        and _save_quick(request, workspace, form)
    ):
        _store(request, workspace, None)
        target = reverse("ledger:movements", args=[workspace.pk])
        if request.headers.get("HX-Request"):
            response = HttpResponse(status=204)
            response["HX-Redirect"] = target
            return response
        return redirect(target)
    errors = "; ".join(f"{' '.join(messages)}" for messages in form.errors.values())
    state["messages"].append(
        {
            "rol": "sophia",
            "texto": "No pude guardarlo"
            + (f": {errors}" if errors else ".")
            + " Corrígelo aquí o termina en el formulario.",
            "enlaces": [
                {
                    "texto": "Abrir el formulario",
                    "url": reverse("ledger:new", args=[workspace.pk]) + "?sophia=1",
                }
            ],
        }
    )
    _store(request, workspace, state)
    return _respond(request, workspace, state)


@workspace_required
@require_POST
def restart(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    _store(request, workspace, None)
    return _respond(request, workspace, get_state(request, workspace))
