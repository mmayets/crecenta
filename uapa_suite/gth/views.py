from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import F, Sum
from django.shortcuts import redirect

from portal.modulos import en_preparacion, render_modulo

from .forms import SolicitudForm
from .models import Evaluacion, FichaColaborador, Inscripcion, Solicitud

SLUG = "gth"
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def _evaluacion_pendiente(usuario):
    return Evaluacion.objects.filter(usuario=usuario, anio=date.today().year, completada=False).first()


def _nav(usuario):
    return [
        ("Resumen", "gth:inicio", 0),
        ("Vacaciones", "gth:vacaciones", 0),
        ("Volantes de pago", "gth:volantes", 0),
        ("Evaluación", "gth:evaluacion", 1 if _evaluacion_pendiente(usuario) else 0),
        ("Capacitaciones", "gth:capacitaciones", 0),
        ("Certificaciones", "gth:certificaciones", 0),
    ]


def _horas_capacitacion(usuario, anio):
    """Horas completadas en el año: horas de cada curso ponderadas por su avance."""
    total = (
        Inscripcion.objects.filter(usuario=usuario, anio=anio)
        .aggregate(h=Sum(F("capacitacion__horas") * F("progreso")))["h"]
        or 0
    )
    return round(total / 100)


@login_required
def inicio(request):
    usuario, hoy = request.user, date.today()
    ficha = FichaColaborador.objects.filter(usuario=usuario).first()
    evaluacion = Evaluacion.objects.filter(usuario=usuario, anio=hoy.year).first()
    anios = ficha.antiguedad_anios(hoy) if ficha else None
    return render_modulo(
        request, "gth/inicio.html", SLUG, _nav(usuario), "gth:inicio",
        {
            "ficha": ficha,
            "antiguedad": "—" if anios is None else f"{anios} año{'' if anios == 1 else 's'}",
            "horas": _horas_capacitacion(usuario, hoy.year),
            "meta_horas": f"Meta anual: {ficha.meta_horas_capacitacion}" if ficha else "",
            "evaluacion": evaluacion,
            "etiqueta_evaluacion": f"Evaluación {hoy.year}",
            "vence_evaluacion": f"Vence {evaluacion.vence.day} {MESES[evaluacion.vence.month - 1]}" if evaluacion else "",
            "solicitudes": Solicitud.objects.filter(usuario=usuario)[:4],
            "capacitaciones": Inscripcion.objects.filter(usuario=usuario, anio=hoy.year, recomendada=True)
            .select_related("capacitacion"),
        },
    )


def _lista(request, activo, titulo, subtitulo, qs):
    return render_modulo(
        request, "gth/solicitudes.html", SLUG, _nav(request.user), activo,
        {"titulo": titulo, "subtitulo": subtitulo, "solicitudes": qs,
         "ficha": FichaColaborador.objects.filter(usuario=request.user).first()},
    )


@login_required
def solicitudes(request):
    return _lista(request, "gth:inicio", "Historial de solicitudes", "Todas tus solicitudes a Gestión Humana",
                  Solicitud.objects.filter(usuario=request.user))


@login_required
def vacaciones(request):
    return _lista(request, "gth:vacaciones", "Vacaciones", "Tus solicitudes de vacaciones",
                  Solicitud.objects.filter(usuario=request.user, tipo=Solicitud.Tipo.VACACIONES))


@login_required
def capacitaciones(request):
    return render_modulo(
        request, "gth/capacitaciones.html", SLUG, _nav(request.user), "gth:capacitaciones",
        {"inscripciones": Inscripcion.objects.filter(usuario=request.user).select_related("capacitacion")
         .order_by("-anio", "capacitacion__nombre")},
    )


@login_required
def evaluacion(request):
    return render_modulo(
        request, "gth/evaluacion.html", SLUG, _nav(request.user), "gth:evaluacion",
        {"evaluaciones": Evaluacion.objects.filter(usuario=request.user)},
    )


@login_required
def volantes(request):
    return en_preparacion(request, SLUG, _nav(request.user), "gth:volantes", "Volantes de pago")


@login_required
def certificaciones(request):
    return en_preparacion(request, SLUG, _nav(request.user), "gth:certificaciones", "Certificaciones")


@login_required
def nueva_solicitud(request):
    form = SolicitudForm(request.POST or None, initial={"tipo": request.GET.get("tipo")})
    if request.method == "POST" and form.is_valid():
        form.instance.usuario = request.user
        form.save()
        messages.success(request, "Solicitud enviada a Gestión Humana.")
        return redirect("gth:inicio")
    return render_modulo(
        request, "portal/formulario.html", SLUG, _nav(request.user), "gth:inicio",
        {"titulo": "Nueva solicitud", "subtitulo": "Gestión Humana te responderá por esta vía.",
         "form": form, "boton": "Enviar solicitud", "volver": "gth:inicio"},
    )
