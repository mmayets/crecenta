from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .forms import UsageForm
from .mixins import SESSION_KEY, workspace_required
from .models import Workspace
from .services.workspaces import create_workspaces_for_usage, default_workspace


@login_required
def home(request: HttpRequest) -> HttpResponse:
    """Entrada de la app: abre el último espacio usado o pide elegir el uso."""
    workspace = default_workspace(request.user, request.session.get(SESSION_KEY))
    if workspace is None:
        return redirect("workspaces:usage")
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
        )
        target = created[0] if created else default_workspace(request.user)
        return redirect("espacio:dashboard", ws=target.pk)
    return render(request, "workspaces/usage.html", {"form": form})


@login_required
def selector(request: HttpRequest) -> HttpResponse:
    workspaces = Workspace.objects.for_user(request.user).personal_first()
    return render(request, "workspaces/selector.html", {"workspaces": workspaces})


@workspace_required
def dashboard(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    # Provisional: los tableros de persona y negocio se construyen en el paso 10.
    return render(request, "workspaces/dashboard.html", {"workspace": workspace})
