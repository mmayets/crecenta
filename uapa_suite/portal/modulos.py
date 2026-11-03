"""Piezas comunes de los módulos internos (PopIn, GTH, Presupuesto, SIES)."""

from dataclasses import dataclass

from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.urls import reverse

from .context_processors import aplicaciones_de
from .models import Aplicacion


@dataclass
class ItemNav:
    etiqueta: str
    url: str
    badge: int = 0
    activo: bool = False


def render_modulo(request, plantilla, slug, items, activo, contexto=None):
    """Renderiza una página dentro del marco del módulo.

    `items` es una lista de (etiqueta, nombre_de_url, contador); `activo` es el nombre de URL marcado.
    Si el perfil del usuario restringe aplicaciones y esta no está incluida, responde 403.
    """
    app = Aplicacion.objects.filter(slug=slug).first()
    if app is not None and not aplicaciones_de(request.user).filter(pk=app.pk).exists():
        raise PermissionDenied
    nav = [ItemNav(etiqueta, reverse(nombre), badge, nombre == activo) for etiqueta, nombre, badge in items]
    return render(
        request,
        plantilla,
        {"modulo_slug": slug, "modulo_app": app, "modulo_nav": nav, **(contexto or {})},
    )


def en_preparacion(request, slug, items, activo, titulo):
    return render_modulo(request, "portal/en_preparacion.html", slug, items, activo, {"titulo": titulo})
