from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.reports.services.business_dashboard import (
    build_business_dashboard,
    build_seller_dashboard,
)
from apps.reports.services.dashboard import build_personal_dashboard

from .forms import UsageForm
from .mixins import SESSION_KEY, workspace_required
from .models import Workspace
from .permissions import FINANZAS, VENDER, can
from .services.workspaces import create_workspaces_for_usage, default_workspace


def home(request: HttpRequest) -> HttpResponse:
    """Entrada de la app.

    - Sin sesión en la web: la página de inicio pública (qué es Crecenta y sus planes).
    - Sin sesión en la PWA instalada (``?origen=pwa``, inicio del manifest): el login.
    - Con sesión: el último espacio usado, o el paso a paso de Sophia para crear el primero.
    """
    if not request.user.is_authenticated:
        if request.GET.get("origen") == "pwa":
            return redirect("account_login")
        from django.conf import settings

        from apps.core.plans import PLANS

        return render(
            request,
            "public/home.html",
            {"plans": PLANS, "google_login": settings.SOCIALACCOUNT_ENABLED_GOOGLE},
        )
    workspace = default_workspace(request.user, request.session.get(SESSION_KEY))
    if workspace is None:
        return redirect("asistente:first_space")
    return redirect("espacio:dashboard", ws=workspace.pk)


@login_required
@require_http_methods(["GET", "POST"])
def usage(request: HttpRequest) -> HttpResponse:
    """Paso 0 del onboarding: crea los espacios persona / negocio / ambos."""
    form = UsageForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        created = create_workspaces_for_usage(
            request.user,
            form.cleaned_data["usage"],
            currency=form.cleaned_data["currency"],
            business_name=form.cleaned_data["business_name"] or None,
            business_currency=form.cleaned_data["business_currency"] or None,
        )
        target = created[0] if created else default_workspace(request.user)
        if created and target.is_personal:
            return redirect("onboarding:index", ws=target.pk)
        return redirect("espacio:dashboard", ws=target.pk)
    return render(request, "workspaces/usage.html", {"form": form})


@login_required
def selector(request: HttpRequest) -> HttpResponse:
    workspaces = Workspace.objects.for_user(request.user).personal_first()
    return render(request, "workspaces/selector.html", {"workspaces": workspaces})


@workspace_required(perm=VENDER)
def dashboard(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    if workspace.is_business and not can(request.workspace_role, FINANZAS):  # type: ignore[attr-defined]
        seller = build_seller_dashboard(workspace, request.user, timezone.localdate())
        return render(
            request, "workspaces/dashboard_seller.html", {"workspace": workspace, "d": seller}
        )
    if workspace.is_business:
        business = build_business_dashboard(workspace, timezone.localdate())
        return render(
            request, "workspaces/dashboard_business.html", {"workspace": workspace, "d": business}
        )
    data = build_personal_dashboard(workspace, timezone.localdate())
    chart = {
        "labels": list(data.spending_by_group),
        "series": [float(v) for v in data.spending_by_group.values()],
    }
    return render(
        request,
        "workspaces/dashboard_personal.html",
        {"workspace": workspace, "d": data, "chart": chart},
    )


@workspace_required(perm=VENDER)
def settings_hub(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    return render(request, "workspaces/settings.html", {"workspace": workspace})
