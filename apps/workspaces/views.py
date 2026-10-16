from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.ledger.models import Account
from apps.personal.models import PersonalProfile
from apps.personal.services.auto_record import record_due
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
    # Si celery beat no corrió todavía hoy, el panel no debe mostrar el saldo sin el sueldo del día.
    record_due(workspace, timezone.localdate())
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
@require_http_methods(["GET", "POST"])
def settings_hub(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    context: dict = {"workspace": workspace}
    if workspace.is_personal:
        profile = PersonalProfile.objects.filter(workspace=workspace).first()
        accounts = Account.objects.for_workspace(workspace).filter(
            is_archived=False, is_savings=False
        )
        if request.method == "POST":
            # Registro automático de cobros y pagos fijos (ver personal/services/auto_record.py).
            enabled = request.POST.get("auto_record") == "on"
            account = accounts.filter(pk=request.POST.get("auto_account") or None).first()
            was_enabled = bool(profile and profile.auto_record)
            PersonalProfile.objects.update_or_create(
                workspace=workspace,
                defaults={
                    "auto_record": enabled,
                    "auto_account": account,
                    # Al encenderlo se empieza desde hoy: no se llenan meses pasados.
                    "auto_since": timezone.localdate()
                    if enabled and not was_enabled
                    else (profile.auto_since if profile else None),
                },
            )
            messages.success(
                request,
                "Listo: tu sueldo y tus pagos fijos se anotarán solos en su fecha."
                if enabled
                else "Listo: ya no se anotan solos tus cobros ni tus pagos fijos.",
            )
            return redirect("espacio:settings", ws=workspace.pk)
        context.update({"profile": profile, "accounts": accounts})
    return render(request, "workspaces/settings.html", context)
