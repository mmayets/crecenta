"""Chat del asistente que guía la creación de espacios (ver `services/assistant.py`)."""

from __future__ import annotations

from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.core.ratelimit import hit
from apps.workspaces.mixins import workspace_required
from apps.workspaces.models import Workspace
from apps.workspaces.permissions import VENDER

from .models import AssistantSession
from .services import assistant
from .services import guide as guide_service
from .views import transcribe_upload

Stage = AssistantSession.Stage


def _context(request: HttpRequest, session: AssistantSession) -> dict:
    draft = session.draft
    current = assistant.current_workspace(session) if session.stage == Stage.FILLING else None
    return {
        "session": session,
        "stage": session.stage,
        "draft": draft,
        "usage_label": {
            "persona": "Mi dinero personal",
            "negocio": "Mi negocio",
            "ambos": "Mi dinero y mi negocio",
        }.get(draft.get("uso") or ""),
        "currency_label": assistant.CURRENCY_LABELS.get(draft.get("moneda") or ""),
        "business_currency_label": assistant.CURRENCY_LABELS.get(draft.get("moneda_negocio") or ""),
        "proposal": assistant.proposal(session) if session.stage == Stage.SUMMARY else [],
        "quick_replies": assistant.quick_replies(session),
        "created": assistant.created_workspaces(session),
        "current": current,
        "needs_ai": session.stage == Stage.FILLING and not request.user.ai_consent,
        "ai_off": not request.user.ai_consent,
    }


def _respond(request: HttpRequest, session: AssistantSession) -> HttpResponse:
    """htmx recibe solo el panel del chat; sin htmx, se vuelve a la página (POST → GET)."""
    if request.headers.get("HX-Request"):
        return render(request, "onboarding/_assistant.html", _context(request, session))
    return redirect("asistente:chat")


@login_required
@require_http_methods(["GET", "POST"])
def chat(request: HttpRequest) -> HttpResponse:
    session = assistant.get_or_start(request.user)
    if request.method == "POST":
        if hit(f"asistente:{request.user.pk}", settings.SYNC_RATE_LIMITS):
            assistant.take_turn(session, request.POST.get("texto", ""))
        return _respond(request, session)
    assistant.sync(session)
    return render(request, "onboarding/assistant.html", _context(request, session))


@login_required
@require_POST
def create(request: HttpRequest) -> HttpResponse:
    session = assistant.get_or_start(request.user)
    assistant.confirm(session)
    return _respond(request, session)


@login_required
@require_POST
def skip(request: HttpRequest) -> HttpResponse:
    session = assistant.get_or_start(request.user)
    assistant.skip(session)
    return _respond(request, session)


@login_required
@require_POST
def restart(request: HttpRequest) -> HttpResponse:
    return _respond(request, assistant.start(request.user))


@login_required
@require_POST
def enable_ai(request: HttpRequest) -> HttpResponse:
    """Consentimiento de IA dado desde el chat (equivale a la casilla de Configuración)."""
    if not request.user.ai_consent:
        request.user.set_ai_consent(True)
    session = assistant.get_or_start(request.user)
    session.say("Gracias, ya puedo entender lo que me escribas o dictes.")
    session.save()
    return _respond(request, session)


@login_required
@require_POST
def voice(request: HttpRequest) -> JsonResponse:
    return transcribe_upload(request, None)


# ---------------------------------------------------------------- asistente permanente


@workspace_required(perm=VENDER)
@require_GET
def guide(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    """Panel flotante: recomendaciones del momento y consejo de la pantalla actual."""
    view_name = request.GET.get("vista", "")[:60]
    here = urlparse(request.headers.get("HX-Current-URL", "")).path
    items = [
        s
        for s in guide_service.suggestions(
            workspace,
            request.user,
            request.workspace_role,  # type: ignore[attr-defined]
            timezone.localdate(),
        )
        if s.url != here  # no recomendar la pantalla en la que ya está
    ]
    return render(
        request,
        "onboarding/_guide.html",
        {
            "workspace": workspace,
            "view_name": view_name,
            "suggestions": items[:4],
            "top": items[0] if items else None,
            "urgent": sum(1 for s in items if s.tone == guide_service.URGENT),
            "tip": guide_service.page_tip(view_name),
        },
    )


@workspace_required(perm=VENDER)
@require_POST
def ask(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    question = request.POST.get("pregunta", "").strip()
    if not question:
        return HttpResponse("")
    if not hit(f"asistente:{request.user.pk}", settings.SYNC_RATE_LIMITS):
        return HttpResponse("", status=429)
    reply = guide_service.answer(
        workspace,
        request.user,
        request.workspace_role,  # type: ignore[attr-defined]
        question,
        request.POST.get("vista", "")[:60],
        timezone.localdate(),
    )
    return render(request, "onboarding/_guide_answer.html", {"reply": reply})
