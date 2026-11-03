import csv
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from portal.modulos import en_preparacion, render_modulo

from .forms import SolicitudCompraForm
from .models import Departamento, SolicitudCompra, totales

SLUG = "presupuesto"
ABIERTAS = [SolicitudCompra.Estado.PENDIENTE, SolicitudCompra.Estado.EN_CURSO]


def _anio(request) -> int:
    valor = request.GET.get("anio", "")
    return int(valor) if valor.isdigit() and 2000 <= int(valor) <= 2100 else date.today().year


def _kpi_ctx(anio):
    t = totales(anio)
    return {"anio": anio, "t": t, "nota_anio": f"Año fiscal {anio}", "nota_ejecutado": f"{t['porcentaje']}% del total"}


def _nav():
    return [
        ("Tablero", "presupuesto:inicio", 0),
        ("Solicitudes", "presupuesto:solicitudes", SolicitudCompra.objects.filter(estado__in=ABIERTAS).count()),
        ("Partidas", "presupuesto:partidas", 0),
        ("Reportes", "presupuesto:reportes", 0),
        ("Proveedores", "presupuesto:proveedores", 0),
    ]


@login_required
def inicio(request):
    anio = _anio(request)
    departamentos = list(Departamento.objects.filter(anio=anio))
    return render_modulo(
        request, "presupuesto/inicio.html", SLUG, _nav(), "presupuesto:inicio",
        {**_kpi_ctx(anio), "departamentos": departamentos,
         "solicitudes": SolicitudCompra.objects.select_related("departamento")[:4]},
    )


@login_required
def solicitudes(request):
    estado = request.GET.get("estado", "")
    qs = SolicitudCompra.objects.select_related("departamento", "solicitante")
    if estado in SolicitudCompra.Estado.values:
        qs = qs.filter(estado=estado)
    return render_modulo(
        request, "presupuesto/solicitudes.html", SLUG, _nav(), "presupuesto:solicitudes",
        {"solicitudes": qs, "estado": estado, "estados": SolicitudCompra.Estado.choices,
         "puede_decidir": request.user.has_perm("presupuesto.decidir_solicitudcompra")},
    )


@login_required
@require_POST
@permission_required("presupuesto.decidir_solicitudcompra", raise_exception=True)
def decidir(request, numero):
    solicitud = get_object_or_404(SolicitudCompra, numero=numero)
    nuevo = request.POST.get("estado")
    if nuevo in SolicitudCompra.Estado.values:
        solicitud.estado = nuevo
        solicitud.save(update_fields=["estado"])
        messages.success(request, f"Solicitud #{numero}: {solicitud.get_estado_display().lower()}.")
    return redirect(request.POST.get("next") or "presupuesto:solicitudes")


@login_required
def partidas(request):
    anio = _anio(request)
    return render_modulo(
        request, "presupuesto/partidas.html", SLUG, _nav(), "presupuesto:partidas",
        {**_kpi_ctx(anio), "departamentos": Departamento.objects.filter(anio=anio)},
    )


@login_required
def exportar_partidas(request):
    anio = _anio(request)
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="ejecucion-{anio}.csv"'
    resp.write("﻿")
    w = csv.writer(resp)
    w.writerow(["Departamento", "Aprobado", "Ejecutado", "Comprometido", "% ejecutado"])
    for d in Departamento.objects.filter(anio=anio):
        w.writerow([d.nombre, d.aprobado, d.ejecutado, d.comprometido, d.porcentaje_ejecutado])
    return resp


@login_required
def reportes(request):
    return en_preparacion(request, SLUG, _nav(), "presupuesto:reportes", "Reportes")


@login_required
def proveedores(request):
    return en_preparacion(request, SLUG, _nav(), "presupuesto:proveedores", "Proveedores")


@login_required
def nueva_solicitud(request):
    form = SolicitudCompraForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.instance.solicitante = request.user
        s = form.save()
        messages.success(request, f"Solicitud de compra #{s.numero} registrada.")
        return redirect("presupuesto:solicitudes")
    return render_modulo(
        request, "portal/formulario.html", SLUG, _nav(), "presupuesto:solicitudes",
        {"titulo": "Solicitud de compra", "subtitulo": "Quedará pendiente de aprobación.",
         "form": form, "boton": "Registrar solicitud", "volver": "presupuesto:inicio"},
    )
