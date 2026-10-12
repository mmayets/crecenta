from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from .forms import DeleteAccountForm, SettingsForm
from .services.privacy import build_export, delete_account


@login_required
@require_http_methods(["GET", "POST"])
def settings_view(request: HttpRequest) -> HttpResponse:
    user = request.user
    form = SettingsForm(
        request.POST or None, instance=user, initial={"ai_consent": user.ai_consent}
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        if form.cleaned_data["ai_consent"] != user.ai_consent:
            user.set_ai_consent(form.cleaned_data["ai_consent"])
        messages.success(request, "Configuración guardada.")
        return redirect("accounts:settings")
    return render(request, "accounts/settings.html", {"form": form})


@login_required
@require_GET
def export_view(request: HttpRequest) -> FileResponse:
    response = FileResponse(
        build_export(request.user),
        as_attachment=True,
        filename=f"crecenta-mis-datos-{timezone.localdate():%Y%m%d}.zip",
        content_type="application/zip",
    )
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_http_methods(["GET", "POST"])
def delete_view(request: HttpRequest) -> HttpResponse:
    form = DeleteAccountForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = request.user
        logout(request)
        delete_account(user)
        messages.info(request, "Tu cuenta y todos tus datos fueron eliminados.")
        return redirect("account_login")
    return render(request, "accounts/delete.html", {"form": form})
