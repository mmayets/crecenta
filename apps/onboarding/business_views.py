"""Onboarding de negocio: mismas URL que el personal (las vistas de `views.py` delegan aquí cuando
el espacio es de negocio). Datos mínimos (perfil y productos) → primer plan de negocio."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django import forms
from django.contrib import messages
from django.db import transaction
from django.forms import modelformset_factory
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.ai.schemas import BusinessOnboardingExtraction
from apps.ai.services.client import AIUnavailable
from apps.ledger.choices import AccountType
from apps.ledger.models import Account
from apps.ledger.system_categories import DEFAULT_ACCOUNT_NAME
from apps.planning.services.generate import request_business_plan
from apps.workspaces.models import Workspace

from .business_forms import (
    BUSINESS_SECTION_FORMS,
    BUSINESS_SINGLE_FORMS,
    BusinessConversationForm,
    GoalForm,
    ProfileForm,
)
from .forms import WorkspaceFormSet, formset_class
from .services.business_conversational import (
    extract_business_from_text,
    to_business_initial,
)
from .services.steps import (
    BUSINESS_STEP_KEYS,
    BUSINESS_STEPS_BY_KEY,
    completeness,
    get_state,
    next_step,
    previous_step,
)


def _build_form(step: str, workspace: Workspace, data=None):
    if step in BUSINESS_SECTION_FORMS:
        form_class = BUSINESS_SECTION_FORMS[step]
        existing = form_class._meta.model.objects.for_workspace(workspace).exists()
        return formset_class(form_class, extra=1 if existing else 2)(
            data, workspace=workspace, prefix=step
        )
    return BUSINESS_SINGLE_FORMS[step](data, workspace=workspace)


def first_pending(workspace: Workspace) -> str:
    for item in completeness(workspace).steps:
        if not item.done and (item.step.required or not item.skipped):
            return item.step.key
    return "listo"


def step(request: HttpRequest, workspace: Workspace, step: str) -> HttpResponse:
    if step not in BUSINESS_STEP_KEYS:
        raise Http404("Paso inexistente")
    info = BUSINESS_STEPS_BY_KEY[step]
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
            "is_formset": step in BUSINESS_SECTION_FORMS,
            "progress": completeness(workspace),
            "previous": previous_step(step, BUSINESS_STEP_KEYS),
            "first_step": BUSINESS_STEP_KEYS[0],
        },
        status=400 if request.method == "POST" else 200,
    )


def _go_next(workspace: Workspace, current: str) -> HttpResponse:
    following = next_step(current, BUSINESS_STEP_KEYS)
    if following is None:
        return redirect("onboarding:done", ws=workspace.pk)
    return redirect("onboarding:step", ws=workspace.pk, step=following)


def done(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    progress = completeness(workspace)
    if request.method == "POST":
        if not progress.minimum_ready:
            messages.error(request, "Cuéntanos a qué se dedica tu negocio y qué vende primero.")
            return redirect("onboarding:index", ws=workspace.pk)
        state = get_state(workspace)
        state.finished_at = state.finished_at or timezone.now()
        state.save()
        plan = request_business_plan(workspace, request.user, timezone.localdate())
        return redirect("planning:detail", ws=workspace.pk, plan_id=plan.pk)
    return render(
        request,
        "onboarding/done.html",
        {"workspace": workspace, "progress": progress, "is_business": True},
    )


# ---------------------------------------------------------------- modo conversacional


def conversation(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    form = BusinessConversationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            extraction = extract_business_from_text(
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
            "first_step": BUSINESS_STEP_KEYS[0],
            "is_business": True,
        },
    )


class CashForm(forms.Form):
    efectivo = forms.DecimalField(
        label="Dinero que tiene hoy el negocio (en efectivo y cuentas)",
        min_value=0,
        max_digits=14,
        decimal_places=2,
        required=False,
    )


def _confirmation_forms(workspace: Workspace, initial: dict[str, Any], data=None):
    formsets = {}
    for section in ("productos", "gastos"):
        rows = initial[section]
        form_class = BUSINESS_SECTION_FORMS[section]
        factory = modelformset_factory(
            form_class._meta.model,
            form=form_class,
            formset=WorkspaceFormSet,
            extra=len(rows),
            can_delete=True,
        )
        formset = factory(
            data,
            workspace=workspace,
            prefix=section,
            queryset=form_class._meta.model.objects.none(),
            initial=rows,
        )
        for i, form in enumerate(formset.forms):
            # Cada fila extraída se guarda aunque no se edite (salvo que la persona la quite).
            form.empty_permitted = False
            form.has_changed = lambda: True  # type: ignore[method-assign]
            for name, field in form.fields.items():
                if f"{section}-{i}-{name}" in initial["dudosos"]:
                    field.widget.attrs.update({"class": "dudoso", "data-dudoso": "1"})
        formsets[section] = formset
    profile = ProfileForm(data, workspace=workspace, initial=initial["perfil"], prefix="perfil")
    goals = GoalForm(data, workspace=workspace, initial=initial["objetivos"], prefix="objetivos")
    cash = CashForm(data, initial={"efectivo": initial["efectivo"]}, prefix="efectivo")
    return profile, formsets, cash, goals


def _save_cash(workspace: Workspace, amount: Decimal) -> None:
    account = (
        Account.objects.for_workspace(workspace).filter(name=DEFAULT_ACCOUNT_NAME).first()
        or Account.objects.for_workspace(workspace).first()
    )
    if account is None:
        Account.objects.create(
            workspace=workspace,
            name=DEFAULT_ACCOUNT_NAME,
            type=AccountType.EFECTIVO,
            currency=workspace.currency,
            opening_balance=amount,
        )
        return
    account.opening_balance = amount
    account.save(update_fields=["opening_balance", "updated_at"])


def confirm(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    state = get_state(workspace)
    if not state.pending_extraction:
        return redirect("onboarding:conversation", ws=workspace.pk)
    extraction = BusinessOnboardingExtraction.model_validate(state.pending_extraction)
    initial = to_business_initial(workspace, extraction)
    profile, formsets, cash, goals = _confirmation_forms(workspace, initial, request.POST or None)
    if request.method == "POST":
        valid = (
            profile.is_valid()
            & all([fs.is_valid() for fs in formsets.values()])
            & cash.is_valid()
            & goals.is_valid()
        )
        if valid:
            with transaction.atomic():
                profile.save()
                state.mark("perfil")
                for section, formset in formsets.items():
                    if formset.save():
                        state.mark(section)
                if cash.cleaned_data.get("efectivo") is not None:
                    _save_cash(workspace, cash.cleaned_data["efectivo"])
                    state.mark("efectivo")
                if any(v not in (None, "") for v in goals.cleaned_data.values()):
                    goals.save()
                    state.mark("objetivos")
                state.pending_extraction = None
                state.save()
            messages.success(request, "¡Listo! Guardamos los datos de tu negocio.")
            return redirect("onboarding:index", ws=workspace.pk)
    return render(
        request,
        "onboarding/confirm_business.html",
        {
            "workspace": workspace,
            "profile": profile,
            "formsets": formsets,
            "cash": cash,
            "goals": goals,
            "has_doubts": bool(initial["dudosos"]),
        },
        status=400 if request.method == "POST" else 200,
    )
