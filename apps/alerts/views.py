from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from apps.workspaces.mixins import workspace_required
from apps.workspaces.models import Workspace

from .models import Alert, AlertRule
from .services.evaluate import catalog


def _get_alert(workspace: Workspace, alert_id) -> Alert:
    try:
        return Alert.objects.for_workspace(workspace).get(pk=alert_id)
    except (Alert.DoesNotExist, ValidationError, ValueError) as exc:
        raise Http404("Alerta no encontrada") from exc


@workspace_required
@require_http_methods(["GET"])
def index(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    alerts = Alert.objects.for_workspace(workspace)
    open_alerts = list(alerts.filter(status__in=Alert.OPEN))
    closed = alerts.exclude(status__in=Alert.OPEN)[:20]
    response = render(
        request,
        "alerts/index.html",
        {"workspace": workspace, "open_alerts": open_alerts, "closed": closed},
    )
    # Al verlas, las nuevas pasan a vistas.
    alerts.filter(status=Alert.Status.NUEVA).update(status=Alert.Status.VISTA)
    return response


@workspace_required
@require_POST
def dismiss(request: HttpRequest, workspace: Workspace, alert_id) -> HttpResponse:
    alert = _get_alert(workspace, alert_id)
    alert.status = Alert.Status.DESCARTADA
    alert.save(update_fields=["status", "updated_at"])
    messages.info(request, "Alerta descartada. No volverá a aparecer en este período.")
    return redirect("alerts:index", ws=workspace.pk)


@workspace_required
@require_POST
def resolve(request: HttpRequest, workspace: Workspace, alert_id) -> HttpResponse:
    alert = _get_alert(workspace, alert_id)
    alert.status = Alert.Status.RESUELTA
    alert.resolved_at = timezone.now()
    alert.save(update_fields=["status", "resolved_at", "updated_at"])
    return redirect("alerts:index", ws=workspace.pk)


class RulesForm(forms.Form):
    def __init__(self, workspace: Workspace, rules: dict[str, AlertRule], *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        defaults_by_code, labels = catalog(workspace)
        for code, defaults in defaults_by_code.items():
            rule = rules.get(code)
            self.fields[f"{code}__enabled"] = forms.BooleanField(
                label=labels[code], required=False, initial=rule.enabled if rule else True
            )
            for name, default in defaults.items():
                value = (rule.params.get(name) if rule else None) or default
                self.fields[f"{code}__{name}"] = forms.IntegerField(
                    label=name.replace("_", " ").capitalize(),
                    min_value=1,
                    max_value=100 if name.endswith("_pct") else 1_000_000,
                    initial=value,
                    required=False,  # vacío = valor por defecto
                )


@workspace_required
@require_http_methods(["GET", "POST"])
def rules(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    existing = {r.code: r for r in AlertRule.objects.for_workspace(workspace)}
    form = RulesForm(workspace, existing, request.POST or None)
    if request.method == "POST" and form.is_valid():
        for code, defaults in catalog(workspace)[0].items():
            AlertRule.objects.update_or_create(
                workspace=workspace,
                code=code,
                defaults={
                    "enabled": form.cleaned_data[f"{code}__enabled"],
                    "params": {
                        name: form.cleaned_data[f"{code}__{name}"] or default
                        for name, default in defaults.items()
                    },
                },
            )
        messages.success(request, "Preferencias de alertas guardadas.")
        return redirect("alerts:index", ws=workspace.pk)
    return render(request, "alerts/rules.html", {"workspace": workspace, "form": form})
