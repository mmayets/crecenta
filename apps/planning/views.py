from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.workspaces.mixins import workspace_required
from apps.workspaces.models import Workspace

from .forms import EditPlanForm
from .models import PlanVersion
from .services.generate import request_personal_plan
from .services.lifecycle import (
    PlanError,
    accept_plan,
    active_budget,
    compare_plans,
    discard_plan,
    edit_plan,
)


def _get_plan(workspace: Workspace, plan_id) -> PlanVersion:
    try:
        return PlanVersion.objects.for_workspace(workspace).get(pk=plan_id)
    except (PlanVersion.DoesNotExist, ValidationError, ValueError) as exc:
        raise Http404("Plan no encontrado") from exc


def _today():
    return timezone.localdate()


@workspace_required(kind="personal")
@require_GET
def index(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    plans = PlanVersion.objects.for_workspace(workspace)
    budget = active_budget(workspace, _today())
    proposal = plans.filter(status__in=["propuesta", "generando"]).first()
    return render(
        request,
        "planning/index.html",
        {
            "workspace": workspace,
            "budget": budget,
            "proposal": proposal,
            "history": plans[:20],
        },
    )


@workspace_required(kind="personal")
@require_POST
def generate(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    plan = request_personal_plan(workspace, request.user, _today())
    return redirect("planning:detail", ws=workspace.pk, plan_id=plan.pk)


@workspace_required(kind="personal")
@require_GET
def detail(request: HttpRequest, workspace: Workspace, plan_id) -> HttpResponse:
    plan = _get_plan(workspace, plan_id)
    template = (
        "planning/_plan.html" if request.headers.get("HX-Request") else "planning/detail.html"
    )
    return render(request, template, {"workspace": workspace, "plan": plan})


@workspace_required(kind="personal")
@require_POST
def accept(request: HttpRequest, workspace: Workspace, plan_id) -> HttpResponse:
    plan = _get_plan(workspace, plan_id)
    try:
        accept_plan(plan, request.user)
        messages.success(request, "Plan aceptado. Tu presupuesto del período quedó listo.")
    except PlanError as exc:
        messages.error(request, str(exc))
    return redirect("planning:detail", ws=workspace.pk, plan_id=plan.pk)


@workspace_required(kind="personal")
@require_POST
def discard(request: HttpRequest, workspace: Workspace, plan_id) -> HttpResponse:
    plan = _get_plan(workspace, plan_id)
    try:
        discard_plan(plan, request.user)
        messages.info(request, "Propuesta descartada.")
    except PlanError as exc:
        messages.error(request, str(exc))
    return redirect("planning:index", ws=workspace.pk)


@workspace_required(kind="personal")
@require_http_methods(["GET", "POST"])
def edit(request: HttpRequest, workspace: Workspace, plan_id) -> HttpResponse:
    plan = _get_plan(workspace, plan_id)
    if not plan.is_open:
        messages.error(request, "Solo se puede editar una propuesta.")
        return redirect("planning:detail", ws=workspace.pk, plan_id=plan.pk)
    form = EditPlanForm(plan, request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            new_plan = edit_plan(plan, request.user, form.to_edits(), _today())
        except (ValidationError, PlanError) as exc:
            form.add_error(None, exc.messages if isinstance(exc, ValidationError) else str(exc))
        else:
            return redirect("planning:detail", ws=workspace.pk, plan_id=new_plan.pk)
    return render(
        request, "planning/edit.html", {"workspace": workspace, "plan": plan, "form": form}
    )


@workspace_required(kind="personal")
@require_GET
def compare(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    a = _get_plan(workspace, request.GET.get("a"))
    b = _get_plan(workspace, request.GET.get("b"))
    return render(
        request,
        "planning/compare.html",
        {"workspace": workspace, "a": a, "b": b, "rows": compare_plans(a, b)},
    )


@workspace_required(kind="personal")
@require_POST
def apply_alternative(request: HttpRequest, workspace: Workspace, plan_id) -> HttpResponse:
    """Crea una nueva propuesta aplicando una alternativa calculada por el motor."""
    plan = _get_plan(workspace, plan_id)
    try:
        new_plan = edit_plan(
            plan, request.user, {"alternativa": request.POST.get("alternativa", "")}, _today()
        )
    except (ValidationError, PlanError) as exc:
        messages.error(
            request, " ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
        )
        return redirect("planning:detail", ws=workspace.pk, plan_id=plan.pk)
    messages.success(request, "Aplicamos la alternativa: revisa la nueva propuesta.")
    return redirect("planning:detail", ws=workspace.pk, plan_id=new_plan.pk)
