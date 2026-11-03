from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .context_processors import aplicaciones_de
from .models import Aviso, EventoAgenda, Notificacion, Pendiente


def saludo(hora: int) -> str:
    if hora < 12:
        return "Buenos días"
    if hora < 19:
        return "Buenas tardes"
    return "Buenas noches"


def _agenda_de_hoy(usuario):
    ahora = timezone.localtime()
    inicio = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    return EventoAgenda.objects.filter(usuario=usuario, inicio__gte=inicio, inicio__lt=inicio + timedelta(days=1))


@login_required
def inicio(request):
    ahora = timezone.localtime()
    usuario = request.user
    return render(
        request,
        "portal/inicio.html",
        {
            "saludo": saludo(ahora.hour),
            "primer_nombre": usuario.first_name or usuario.get_username(),
            "hoy": ahora,
            "aviso": Aviso.vigente(),
            "pendientes": Pendiente.objects.filter(usuario=usuario, completado=False).select_related("aplicacion")[:5],
            "agenda": _agenda_de_hoy(usuario),
        },
    )


@login_required
def pendientes(request):
    estado = request.GET.get("estado", "abiertos")
    qs = Pendiente.objects.filter(usuario=request.user).select_related("aplicacion")
    if estado == "abiertos":
        qs = qs.filter(completado=False)
    elif estado == "completados":
        qs = qs.filter(completado=True)
    return render(request, "portal/pendientes.html", {"pendientes": qs, "estado": estado})


@login_required
@require_POST
def alternar_pendiente(request, pk):
    pendiente = get_object_or_404(Pendiente, pk=pk, usuario=request.user)
    pendiente.completado = not pendiente.completado
    pendiente.save(update_fields=["completado"])
    return redirect(request.POST.get("next") or "portal:pendientes")


@login_required
def notificaciones(request):
    qs = Notificacion.objects.filter(usuario=request.user).select_related("aplicacion")
    return render(request, "portal/notificaciones.html", {"notificaciones": qs})


@login_required
@require_POST
def marcar_leidas(request):
    Notificacion.objects.filter(usuario=request.user, leida=False).update(leida=True)
    return redirect(request.POST.get("next") or "portal:notificaciones")


def _buscar(usuario, q: str):
    apps = aplicaciones_de(usuario).filter(Q(nombre__icontains=q) | Q(descripcion__icontains=q))
    pend = Pendiente.objects.filter(usuario=usuario, titulo__icontains=q).select_related("aplicacion")[:10]
    eventos = EventoAgenda.objects.filter(usuario=usuario, titulo__icontains=q)[:10]
    return apps, pend, eventos


@login_required
def buscar(request):
    q = request.GET.get("q", "").strip()
    apps, pend, eventos = _buscar(request.user, q) if q else ([], [], [])
    if request.headers.get("Accept") == "application/json":
        return JsonResponse(
            {
                "resultados": [
                    *(
                        {"tipo": "Aplicación", "titulo": a.nombre, "detalle": a.descripcion,
                         "url": a.enlace if a.disponible else "", "icono": a.icono, "color": a.color}
                        for a in apps
                    ),
                    *(
                        {"tipo": "Pendiente", "titulo": p.titulo, "detalle": p.aplicacion.nombre,
                         "url": p.enlace, "icono": "check2-square", "color": p.aplicacion.color}
                        for p in pend
                    ),
                    *(
                        {"tipo": "Agenda", "titulo": e.titulo,
                         "detalle": timezone.localtime(e.inicio).strftime("%d/%m %H:%M"),
                         "url": "", "icono": "calendar-event", "color": "popin"}
                        for e in eventos
                    ),
                ]
            }
        )
    return render(request, "portal/buscar.html", {"q": q, "apps": apps, "pendientes": pend, "eventos": eventos})
