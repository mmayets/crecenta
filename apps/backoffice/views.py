"""Panel de administración: resumen, uso y comportamiento, finanzas agregadas, usuarios,
auditoría y parámetros. Solo para el equipo (is_staff); a cualquier otra persona le responde 404."""

from __future__ import annotations

import csv
from collections.abc import Callable
from datetime import datetime, time, timedelta
from functools import wraps
from typing import Any
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import Http404, HttpRequest, HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts.models import PushSubscription, User
from apps.accounts.services import push
from apps.core.models import Parameter

from .forms import ParameterForm, PushForm, is_secret
from .models import AuditEvent
from .services import stats
from .services.audit import Kind, record

PAGE_SIZE = 50


def staff_required(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    @wraps(view)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not (request.user.is_active and request.user.is_staff):
            raise Http404("No encontrado")
        return view(request, *args, **kwargs)

    return wrapper


def _days(request: HttpRequest) -> int:
    value = request.GET.get("dias", "30")
    return int(value) if value in {"7", "30", "90"} else 30


@staff_required
@require_GET
def overview(request: HttpRequest) -> HttpResponse:
    days = _days(request)
    usage = stats.usage(days)
    chart = {
        "labels": usage["labels"],
        "series": [
            {"name": "Personas activas", "data": usage["series"]["activos"]},
            {"name": "Registros nuevos", "data": usage["series"]["registros"]},
            {"name": "Usos de IA", "data": usage["series"]["ia"]},
        ],
    }
    recent = AuditEvent.objects.select_related("user").exclude(kind=Kind.VISITA)[:10]
    return render(
        request,
        "backoffice/overview.html",
        {"tab": "resumen", "days": days, "u": usage, "chart": chart, "recent": recent},
    )


@staff_required
@require_GET
def behavior(request: HttpRequest) -> HttpResponse:
    days = _days(request)
    data = stats.behavior(days)
    hours = {"labels": [f"{h}h" for h in range(24)],
             "series": [{"name": "Eventos", "data": data["hours"]}]}  # fmt: skip
    return render(
        request,
        "backoffice/behavior.html",
        {"tab": "comportamiento", "days": days, "b": data, "hours": hours},
    )


@staff_required
@require_GET
def finances(request: HttpRequest) -> HttpResponse:
    return render(request, "backoffice/finances.html", {"tab": "finanzas", "f": stats.finances()})


@staff_required
@require_GET
def users(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q", "").strip()
    qs = User.objects.annotate(
        spaces=Count("owned_workspaces", distinct=True),
    ).order_by("-date_joined")
    if query:
        qs = qs.filter(Q(email__icontains=query) | Q(first_name__icontains=query))
    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("pagina"))
    return render(
        request,
        "backoffice/users.html",
        {
            "tab": "usuarios",
            "page": page,
            "q": query,
            "extra": urlencode({"q": query}) if query else "",
        },
    )


@staff_required
@require_GET
def user_detail(request: HttpRequest, user_id) -> HttpResponse:
    person = get_object_or_404(User, pk=user_id)
    events = AuditEvent.objects.filter(user=person)
    page = Paginator(events, PAGE_SIZE).get_page(request.GET.get("pagina"))
    summary = events.values("kind").annotate(n=Count("id"))
    return render(
        request,
        "backoffice/user_detail.html",
        {
            "tab": "usuarios",
            "person": person,
            "page": page,
            "summary": {r["kind"]: r["n"] for r in summary},
            "workspaces": person.owned_workspaces.all(),
        },
    )


def _audit_queryset(request: HttpRequest):
    qs = AuditEvent.objects.select_related("user")
    params = request.GET
    if params.get("usuario"):
        qs = qs.filter(user_email__icontains=params["usuario"].strip())
    if params.get("tipo") in Kind.values:
        qs = qs.filter(kind=params["tipo"])
    if params.get("q"):
        text = params["q"].strip()
        qs = qs.filter(
            Q(action__icontains=text) | Q(description__icontains=text) | Q(path__icontains=text)
        )
    if params.get("resultado") == "errores":
        qs = qs.filter(status__gte=400)
    tz = timezone.get_current_timezone()
    since, until = parse_date(params.get("desde", "")), parse_date(params.get("hasta", ""))
    if since:
        qs = qs.filter(created_at__gte=datetime.combine(since, time.min, tz))
    if until:
        qs = qs.filter(created_at__lt=datetime.combine(until + timedelta(days=1), time.min, tz))
    return qs


class _Echo:
    def write(self, value: str) -> str:
        return value


@staff_required
@require_GET
def audit(request: HttpRequest) -> HttpResponse:
    qs = _audit_queryset(request)
    if request.GET.get("formato") == "csv":
        record(kind=Kind.ADMIN, action="panel:auditoria_csv",
               description="Descargó la auditoría en CSV", request=request, status=200)  # fmt: skip
        writer = csv.writer(_Echo())
        header = ["fecha", "correo", "tipo", "acción", "descripción", "método", "ruta",
                  "resultado", "espacio", "ip", "duración_ms"]  # fmt: skip
        rows = (
            [timezone.localtime(e.created_at).isoformat(), e.user_email, e.kind, e.action,
             e.description, e.method, e.path, e.status or "", e.workspace_id or "", e.ip or "",
             e.duration_ms or ""]
            for e in qs.iterator()
        )  # fmt: skip
        response = StreamingHttpResponse(
            (writer.writerow(r) for r in [header, *rows]), content_type="text/csv; charset=utf-8"
        )
        response["Content-Disposition"] = (
            f'attachment; filename="auditoria-{timezone.localdate():%Y%m%d}.csv"'
        )
        return response
    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("pagina"))
    filters = request.GET.copy()
    filters.pop("pagina", None)
    return render(
        request,
        "backoffice/audit.html",
        {"tab": "auditoria", "page": page, "kinds": Kind.choices, "filters": filters.urlencode(),
         "f": request.GET},
    )  # fmt: skip


@staff_required
@require_GET
def parameters(request: HttpRequest) -> HttpResponse:
    items = [
        {"obj": p, "secret": is_secret(p.key), "shown": "••••••" if is_secret(p.key) else p.value}
        for p in Parameter.objects.all()
    ]
    return render(request, "backoffice/parameters.html", {"tab": "parametros", "items": items})


@staff_required
@require_http_methods(["GET", "POST"])
def parameter_edit(request: HttpRequest, parameter_id=None) -> HttpResponse:
    instance = get_object_or_404(Parameter, pk=parameter_id) if parameter_id else None
    before = instance.value if instance else None  # antes de validar: el form cambia la instancia
    form = ParameterForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        changed = before is None or before != saved.value
        record(
            kind=Kind.ADMIN,
            action="panel:parametro_creado" if instance is None else "panel:parametro_editado",
            description=f"{'Creó' if instance is None else 'Editó'} el parámetro {saved.key}",
            request=request,
            status=200,
            data={
                "clave": saved.key,
                "valor_cambiado": changed,
            },  # nunca el valor (puede ser secreto)
        )
        messages.success(
            request, f"Parámetro {saved.key} guardado. Reinicia el servidor para que tome efecto."
        )
        return redirect("panel:parameters")
    return render(
        request,
        "backoffice/parameter_form.html",
        {"tab": "parametros", "form": form, "instance": instance},
        status=400 if request.method == "POST" else 200,
    )


@staff_required
@require_POST
def parameter_delete(request: HttpRequest, parameter_id) -> HttpResponse:
    parameter = get_object_or_404(Parameter, pk=parameter_id)
    key = parameter.key
    parameter.delete()
    record(kind=Kind.ADMIN, action="panel:parametro_eliminado",
           description=f"Eliminó el parámetro {key}", request=request, status=200,
           data={"clave": key})  # fmt: skip
    messages.info(request, f"Parámetro {key} eliminado. Reinicia el servidor para que tome efecto.")
    return redirect("panel:parameters")


@staff_required
@require_http_methods(["GET", "POST"])
def notifications(request: HttpRequest) -> HttpResponse:
    form = PushForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        message = push.PushMessage(title=data["titulo"], body=data["mensaje"], url=data["enlace"])
        if data["destino"] == "una":
            person = User.objects.filter(email__iexact=data["correo"]).first()
            sent = push.send_to_user(person, message) if person else 0
        else:
            sent = push.send_to_everyone(message)
        record(
            kind=Kind.ADMIN,
            action="panel:notificacion_enviada",
            description=f"Envió una notificación push: «{data['titulo']}»",
            request=request,
            status=200,
            data={"destino": data["destino"], "correo": data.get("correo") or "", "enviadas": sent},
        )
        if sent:
            messages.success(request, f"Notificación enviada a {sent} dispositivo(s).")
        else:
            messages.warning(
                request, "No se envió: no hay dispositivos con notificaciones activas."
            )
        return redirect("panel:notifications")
    subscriptions = PushSubscription.objects.filter(user__is_active=True)
    return render(
        request,
        "backoffice/notifications.html",
        {
            "tab": "notificaciones",
            "form": form,
            "enabled": push.enabled(),
            "devices": subscriptions.count(),
            "people": subscriptions.values("user").distinct().count(),
        },
        status=400 if request.method == "POST" else 200,
    )
