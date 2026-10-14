"""Chat de CentIA en «Registrar movimiento» (ver `services/centia.py`).

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
from django.views.decorators.http import require_POST

from apps.core.ratelimit import hit
from apps.workspaces.mixins import workspace_required
from apps.workspaces.models import Workspace

from .services import centia


def _key(workspace: Workspace) -> str:
    return f"centia:{workspace.pk}"


def get_state(request: HttpRequest, workspace: Workspace) -> dict[str, Any]:
    state = request.session.get(_key(workspace))
    if not state:
        state = centia.new_state(workspace, request.user)  # type: ignore[arg-type]
    return state


def _store(request: HttpRequest, workspace: Workspace, state: dict[str, Any] | None) -> None:
    if state is None:
        request.session.pop(_key(workspace), None)
    else:
        request.session[_key(workspace)] = state


def centia_context(
    request: HttpRequest, workspace: Workspace, state: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Lo que necesita `ledger/_centia.html` (también lo usa la vista del formulario)."""
    state = state or get_state(request, workspace)
    return {
        "workspace": workspace,
        "centia": state,
        "centia_replies": centia.quick_replies(workspace, state),
        "centia_proposal": centia.proposal(workspace, state),
        "centia_ai_off": not request.user.ai_consent,  # type: ignore[union-attr]
        "centia_uuid": uuid.uuid4(),
    }


def _respond(request: HttpRequest, workspace: Workspace, state: dict[str, Any]) -> HttpResponse:
    if request.headers.get("HX-Request"):
        return render(request, "ledger/_centia.html", centia_context(request, workspace, state))
    return redirect(reverse("ledger:new", args=[workspace.pk]) + "#texto")


@workspace_required
@require_POST
def message(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    state = get_state(request, workspace)
    if hit(f"centia:{request.user.pk}", settings.SYNC_RATE_LIMITS):
        centia.take_turn(
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
    form = centia.build_form(state, workspace, request.POST.get("client_uuid", ""))
    if (
        centia.proposal(workspace, state)
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
            "rol": "centia",
            "texto": "No pude guardarlo"
            + (f": {errors}" if errors else ".")
            + " Corrígelo aquí o termina en el formulario.",
            "enlaces": [
                {
                    "texto": "Abrir el formulario",
                    "url": reverse("ledger:new", args=[workspace.pk]) + "?centia=1",
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
