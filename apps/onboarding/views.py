from typing import Any

from django.contrib import messages
from django.db import transaction
from django.forms import modelformset_factory
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.ai.providers import Attachment
from apps.ai.schemas import OnboardingExtraction
from apps.ai.services.client import AIUnavailable, transcribe
from apps.personal.models import PersonalProfile
from apps.planning.services.generate import request_personal_plan
from apps.workspaces.mixins import workspace_required
from apps.workspaces.models import Workspace

from . import business_views
from .forms import (
    SECTION_FORMS,
    ConversationForm,
    EssentialsForm,
    PreferencesForm,
    WorkspaceFormSet,
    formset_class,
)
from .services.conversational import extract_from_text, to_initial
from .services.steps import (
    STEP_KEYS,
    STEPS_BY_KEY,
    completeness,
    get_state,
    next_step,
    previous_step,
)

MAX_AUDIO_BYTES = 10 * 1024 * 1024
CONFIRM_SECTIONS = ("ingresos", "cuentas", "compromisos", "deudas", "ahorro")


def _build_form(step: str, workspace: Workspace, data=None):
    if step in SECTION_FORMS:
        form_class = SECTION_FORMS[step]
        existing = form_class._meta.model.objects.for_workspace(workspace).exists()
        return formset_class(form_class, extra=1 if existing else 2)(
            data, workspace=workspace, prefix=step
        )
    if step == "esenciales":
        return EssentialsForm(data, workspace=workspace)
    return PreferencesForm(data, workspace=workspace)


def _first_pending(workspace: Workspace) -> str:
    progress = completeness(workspace)
    for item in progress.steps:
        if not item.done and (item.step.required or not item.skipped):
            return item.step.key
    return "listo"


@workspace_required
@require_GET
def index(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    first = business_views.first_pending if workspace.is_business else _first_pending
    target = first(workspace)
    if target == "listo":
        return redirect("onboarding:done", ws=workspace.pk)
    return redirect("onboarding:step", ws=workspace.pk, step=target)


@workspace_required
@require_http_methods(["GET", "POST"])
def step(request: HttpRequest, workspace: Workspace, step: str) -> HttpResponse:
    if workspace.is_business:
        return business_views.step(request, workspace, step)
    if step not in STEP_KEYS:
        raise Http404("Paso inexistente")
    info = STEPS_BY_KEY[step]
    state = get_state(workspace)
    action = request.POST.get("accion", "siguiente")

    if request.method == "POST" and action == "omitir" and not info.required:
        state.mark(step, skipped=True)
        state.save()
        return _go_next(workspace, step)

    form = _build_form(step, workspace, request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
            state.mark(step)
            state.save()
        if action == "quedarse":
            messages.success(request, "Guardado. Puedes agregar otro.")
            return redirect("onboarding:step", ws=workspace.pk, step=step)
        return _go_next(workspace, step)

    return render(
        request,
        "onboarding/step.html",
        {
            "workspace": workspace,
            "info": info,
            "form": form,
            "is_formset": step in SECTION_FORMS,
            "progress": completeness(workspace),
            "previous": previous_step(step),
            "first_step": STEP_KEYS[0],
        },
        status=400 if request.method == "POST" else 200,
    )


def _go_next(workspace: Workspace, current: str) -> HttpResponse:
    following = next_step(current)
    if following is None:
        return redirect("onboarding:done", ws=workspace.pk)
    return redirect("onboarding:step", ws=workspace.pk, step=following)


@workspace_required
@require_http_methods(["GET", "POST"])
def done(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    if workspace.is_business:
        return business_views.done(request, workspace)
    progress = completeness(workspace)
    if request.method == "POST":
        if not progress.minimum_ready:
            messages.error(request, "Completa ingresos, compromisos y gastos esenciales primero.")
            return redirect("onboarding:index", ws=workspace.pk)
        state = get_state(workspace)
        state.finished_at = state.finished_at or timezone.now()
        state.save()
        plan = request_personal_plan(workspace, request.user, timezone.localdate())
        return redirect("planning:detail", ws=workspace.pk, plan_id=plan.pk)
    return render(request, "onboarding/done.html", {"workspace": workspace, "progress": progress})


# ---------------------------------------------------------------- modo conversacional


@workspace_required
@require_http_methods(["GET", "POST"])
def conversation(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    if workspace.is_business:
        return business_views.conversation(request, workspace)
    form = ConversationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            extraction = extract_from_text(
                workspace, request.user, form.cleaned_data["texto"], timezone.localdate()
            )
        except AIUnavailable as exc:
            form.add_error(None, f"{exc} También puedes usar el formulario paso a paso.")
        else:
            state = get_state(workspace)
            state.pending_extraction = extraction.model_dump(mode="json")
            state.save()
            return redirect("onboarding:confirm", ws=workspace.pk)
    return render(
        request,
        "onboarding/conversation.html",
        {
            "workspace": workspace,
            "form": form,
            "progress": completeness(workspace),
            "first_step": STEP_KEYS[0],
        },
    )


def _confirmation_forms(workspace: Workspace, initial: dict[str, Any], data=None):
    formsets = {}
    for section in CONFIRM_SECTIONS:
        rows = initial[section]
        form_class = SECTION_FORMS[section]
        factory = modelformset_factory(
            form_class._meta.model,
            form=form_class,
            formset=WorkspaceFormSet,
            extra=len(rows),
            can_delete=True,
        )
        formsets[section] = factory(
            data,
            workspace=workspace,
            prefix=section,
            queryset=form_class._meta.model.objects.none(),
            initial=rows,
            form_kwargs={"merge_existing": True} if section == "cuentas" else None,
        )
    essentials = EssentialsForm(data, workspace=workspace, initial=initial["esenciales"])
    for formset in formsets.values():
        for i, form in enumerate(formset.forms):
            # Cada fila extraída se guarda aunque la persona no la edite (salvo que la quite).
            form.empty_permitted = False
            form.has_changed = lambda: True  # type: ignore[method-assign]
            for name, field in form.fields.items():
                if f"{formset.prefix}-{i}-{name}" in initial["dudosos"]:
                    field.widget.attrs.update({"class": "dudoso", "data-dudoso": "1"})
    return formsets, essentials


@workspace_required
@require_http_methods(["GET", "POST"])
def confirm(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    if workspace.is_business:
        return business_views.confirm(request, workspace)
    state = get_state(workspace)
    if not state.pending_extraction:
        return redirect("onboarding:conversation", ws=workspace.pk)
    extraction = OnboardingExtraction.model_validate(state.pending_extraction)
    initial = to_initial(workspace, extraction)
    formsets, essentials = _confirmation_forms(workspace, initial, request.POST or None)

    if request.method == "POST":
        valid = all(fs.is_valid() for fs in formsets.values()) & essentials.is_valid()
        if valid:
            with transaction.atomic():
                for section, formset in formsets.items():
                    if formset.save():
                        state.mark(section)
                if any(essentials.cleaned_data.values()):
                    essentials.save()
                    state.mark("esenciales")
                if extraction.ocio_deseado is not None:
                    PersonalProfile.objects.update_or_create(
                        workspace=workspace,
                        defaults={"discretionary_wish": extraction.ocio_deseado},
                    )
                state.pending_extraction = None
                state.save()
            messages.success(request, "¡Listo! Guardamos tus datos.")
            return redirect("onboarding:index", ws=workspace.pk)

    return render(
        request,
        "onboarding/confirm.html",
        {
            "workspace": workspace,
            "formsets": formsets,
            "essentials": essentials,
            "extraction": extraction,
            "has_doubts": bool(initial["dudosos"]),
            "unmatched": initial["sin_categoria"],
            "progress": completeness(workspace),
        },
        status=400 if request.method == "POST" else 200,
    )


@workspace_required
@require_POST
def voice(request: HttpRequest, workspace: Workspace) -> JsonResponse:
    """Nota de voz → texto (para dictar en el modo conversacional o en el registro rápido)."""
    audio = request.FILES.get("audio")
    if audio is None or not (audio.content_type or "").startswith("audio/"):
        return JsonResponse({"error": "Envía un archivo de audio."}, status=400)
    if audio.size > MAX_AUDIO_BYTES:
        return JsonResponse({"error": "El audio es demasiado largo."}, status=400)
    try:
        text = transcribe(
            workspace=workspace,
            user=request.user,
            audio=Attachment(audio.read(), audio.content_type, audio.name or "nota.webm"),
        )
    except AIUnavailable as exc:
        return JsonResponse({"error": str(exc)}, status=503)
    return JsonResponse({"texto": text})
