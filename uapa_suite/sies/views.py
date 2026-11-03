import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Sum
from django.http import HttpResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from portal.modulos import en_preparacion, render_modulo

from .models import Seccion

SLUG = "sies"
PENDIENTE = Seccion.Calificaciones.PENDIENTE


def _secciones(usuario):
    return Seccion.objects.filter(docente=usuario, activo=True)


def _nav(usuario):
    return [
        ("Secciones", "sies:inicio", 0),
        ("Calificaciones", "sies:calificaciones", _secciones(usuario).filter(calificaciones=PENDIENTE).count()),
        ("Asistencia", "sies:asistencia", 0),
        ("Estudiantes", "sies:estudiantes", 0),
        ("Calendario académico", "sies:calendario", 0),
    ]


def _contexto(usuario):
    qs = _secciones(usuario)
    agg = qs.aggregate(inscritos=Sum("inscritos"), nuevos=Sum("nuevos"), asistencia=Avg("asistencia"))
    por_publicar = qs.filter(calificaciones=PENDIENTE)
    primera = qs.first()
    return {
        "secciones": qs,
        "trimestre": primera.trimestre if primera else "",
        "inscritos": agg["inscritos"] or 0,
        "nuevos": agg["nuevos"] or 0,
        "asistencia": round(agg["asistencia"] or 0),
        "por_publicar": por_publicar,
        "nota_nuevos": f"+{agg['nuevos']} nuevos" if agg["nuevos"] else "",
        "asistencia_texto": f"{round(agg['asistencia'] or 0)}%",
        "nota_por_publicar": ", ".join(s.asignatura for s in por_publicar) or "Todo publicado",
    }


@login_required
def inicio(request):
    return render_modulo(request, "sies/inicio.html", SLUG, _nav(request.user), "sies:inicio", _contexto(request.user))


@login_required
def calificaciones(request):
    return render_modulo(
        request, "sies/calificaciones.html", SLUG, _nav(request.user), "sies:calificaciones", _contexto(request.user)
    )


@login_required
def asistencia(request):
    return render_modulo(
        request, "sies/asistencia.html", SLUG, _nav(request.user), "sies:asistencia", _contexto(request.user)
    )


@login_required
@require_POST
def publicar(request):
    """Envía a revisión las calificaciones pendientes (todas, o solo la sección indicada)."""
    qs = _secciones(request.user).filter(calificaciones=PENDIENTE)
    if request.POST.get("seccion"):
        qs = qs.filter(pk=request.POST["seccion"])
    n = qs.update(calificaciones=Seccion.Calificaciones.EN_CURSO)
    if n:
        messages.success(request, f"Calificaciones enviadas: {n} sección(es) en revisión.")
    else:
        messages.info(request, "No hay calificaciones pendientes de publicar.")
    return redirect(request.POST.get("next") or "sies:inicio")


@login_required
def exportar(request):
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="secciones.csv"'
    resp.write("﻿")
    w = csv.writer(resp)
    w.writerow(["Código", "Asignatura", "Sección", "Inscritos", "Asistencia %", "Calificaciones"])
    for s in _secciones(request.user):
        w.writerow([s.codigo, s.asignatura, f"Sec. {s.numero:02d}", s.inscritos, s.asistencia,
                    s.get_calificaciones_display()])
    return resp


@login_required
def estudiantes(request):
    return en_preparacion(request, SLUG, _nav(request.user), "sies:estudiantes", "Estudiantes")


@login_required
def calendario(request):
    return en_preparacion(request, SLUG, _nav(request.user), "sies:calendario", "Calendario académico")
