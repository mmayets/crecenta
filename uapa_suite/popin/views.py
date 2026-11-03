from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Count, Exists, OuterRef
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from portal.modulos import render_modulo

from .forms import ComentarioForm, ComunicadoForm
from .models import Comunicado

SLUG = "popin"
TITULOS = {
    "comunicado": "Comunicados",
    "noticia": "Noticias",
    "evento": "Eventos",
    "encuesta": "Encuestas",
    "guardados": "Guardados",
}


def _no_leidos(usuario):
    return Comunicado.objects.exclude(leido_por=usuario)


def _nav(usuario):
    sin_leer = dict(_no_leidos(usuario).values_list("tipo").annotate(n=Count("id")))
    return [
        ("Comunicados", "popin:inicio", 0),
        ("Noticias", "popin:noticias", sin_leer.get("noticia", 0)),
        ("Eventos", "popin:eventos", sin_leer.get("evento", 0)),
        ("Encuestas", "popin:encuestas", sin_leer.get("encuesta", 0)),
        ("Guardados", "popin:guardados", 0),
    ]


def _inicio_de_mes(fecha):
    return fecha.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def indicadores(usuario):
    ahora = timezone.localtime()
    mes = _inicio_de_mes(ahora)
    mes_anterior = _inicio_de_mes(mes - timezone.timedelta(days=1))
    este_mes = Comunicado.objects.filter(publicado__gte=mes, publicado__lte=ahora)
    publicados = este_mes.count()
    anterior = Comunicado.objects.filter(publicado__gte=mes_anterior, publicado__lt=mes).count()
    variacion = round((publicados - anterior) * 100 / anterior) if anterior else None
    personal = get_user_model().objects.filter(is_active=True).count() or 1
    lecturas = este_mes.annotate(n=Count("leido_por")).values_list("n", flat=True)
    alcance = round(sum(lecturas) * 100 / (len(lecturas) * personal)) if lecturas else 0
    return {
        "publicados": publicados,
        "variacion": "" if variacion is None else f"{variacion:+d}% vs. mes anterior",
        "alcance": f"{alcance}%",
        "sin_leer": _no_leidos(usuario).filter(publicado__lte=ahora).count(),
    }


def _feed(request, filtro, nombre_url):
    usuario = request.user
    qs = Comunicado.objects.filter(publicado__lte=timezone.now())
    qs = qs.filter(guardado_por=usuario) if filtro == "guardados" else qs.filter(tipo=filtro)
    qs = qs.annotate(
        n_me_gusta=Count("me_gusta", distinct=True),
        n_comentarios=Count("comentarios", distinct=True),
        gustado=Exists(Comunicado.me_gusta.through.objects.filter(comunicado_id=OuterRef("pk"), user_id=usuario.pk)),
        leido=Exists(Comunicado.leido_por.through.objects.filter(comunicado_id=OuterRef("pk"), user_id=usuario.pk)),
    ).order_by("-publicado")[:20]  # Meta.ordering no se aplica en consultas agregadas
    return render_modulo(
        request, "popin/feed.html", SLUG, _nav(usuario), nombre_url,
        {"titulo": TITULOS[filtro], "comunicados": qs, "kpi": indicadores(usuario)},
    )


@login_required
def inicio(request):
    return _feed(request, "comunicado", "popin:inicio")


def _vista(filtro, nombre_url):
    @login_required
    def vista(request):
        return _feed(request, filtro, nombre_url)

    return vista


noticias = _vista("noticia", "popin:noticias")
eventos = _vista("evento", "popin:eventos")
encuestas = _vista("encuesta", "popin:encuestas")
guardados = _vista("guardados", "popin:guardados")


@login_required
def detalle(request, pk):
    comunicado = get_object_or_404(Comunicado, pk=pk)
    if comunicado.publicado > timezone.now() and not request.user.has_perm("popin.change_comunicado"):
        raise Http404
    comunicado.leido_por.add(request.user)
    form = ComentarioForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.instance.comunicado = comunicado
        form.instance.usuario = request.user
        form.save()
        return redirect("popin:detalle", pk=pk)
    nombre_url = {"comunicado": "popin:inicio", "noticia": "popin:noticias", "evento": "popin:eventos",
                  "encuesta": "popin:encuestas"}[comunicado.tipo]
    return render_modulo(
        request, "popin/detalle.html", SLUG, _nav(request.user), nombre_url,
        {
            "c": comunicado,
            "form": form,
            "gustado": comunicado.me_gusta.filter(pk=request.user.pk).exists(),
            "guardado": comunicado.guardado_por.filter(pk=request.user.pk).exists(),
        },
    )


def _alternar(relacion, usuario):
    if relacion.filter(pk=usuario.pk).exists():
        relacion.remove(usuario)
    else:
        relacion.add(usuario)


@login_required
@require_POST
def me_gusta(request, pk):
    _alternar(get_object_or_404(Comunicado, pk=pk).me_gusta, request.user)
    return redirect(request.POST.get("next") or "popin:inicio")


@login_required
@require_POST
def guardar(request, pk):
    _alternar(get_object_or_404(Comunicado, pk=pk).guardado_por, request.user)
    return redirect(request.POST.get("next") or "popin:inicio")


@login_required
@permission_required("popin.add_comunicado", raise_exception=True)
def nuevo(request):
    form = ComunicadoForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.instance.autor = request.user
        c = form.save()
        return redirect("popin:detalle", pk=c.pk)
    return render_modulo(
        request, "portal/formulario.html", SLUG, _nav(request.user), "popin:inicio",
        {"titulo": "Nuevo comunicado", "subtitulo": "Se publicará para todo el personal.", "form": form,
         "boton": "Publicar", "volver": "popin:inicio"},
    )
