import json

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .forms import DeleteAccountForm, SettingsForm
from .services import push
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


# ---------------------------------------------------------------- notificaciones push


def _json(request: HttpRequest) -> dict:
    try:
        return json.loads(request.body or b"{}")
    except ValueError:
        return {}


@login_required
@require_POST
def push_subscribe(request: HttpRequest) -> JsonResponse:
    try:
        push.subscribe(request.user, _json(request), request.META.get("HTTP_USER_AGENT", ""))
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def push_unsubscribe(request: HttpRequest) -> JsonResponse:
    push.unsubscribe(request.user, str(_json(request).get("endpoint", "")))
    return JsonResponse({"ok": True})


@login_required
@require_POST
def push_test(request: HttpRequest) -> JsonResponse:
    sent = push.send_to_user(
        request.user,
        push.PushMessage(
            title="Crecenta",
            body="¡Listo! Así te avisaremos de pagos cercanos, alertas y mensajes importantes.",
            url=reverse("home"),
            tag="prueba",
        ),
    )
    return JsonResponse({"ok": bool(sent), "enviadas": sent}, status=200 if sent else 409)
