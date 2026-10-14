"""Manifest, service worker y páginas sin conexión de la PWA."""

import hashlib
import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.cache import cache_control, never_cache
from django.views.decorators.http import require_GET

from apps.workspaces.mixins import SESSION_KEY
from apps.workspaces.services.workspaces import default_workspace

# Archivos que el service worker guarda al instalarse (la app abre sin conexión).
PRECACHE_STATIC = [
    "css/app.css",
    "js/app.js",
    "js/offline-queue.js",
    "vendor/htmx-2.0.4.min.js",
    "vendor/alpine-csp-3.14.8.min.js",
    "icons/icon-192.png",
    "icons/favicon-32.png",
]


@require_GET
@cache_control(max_age=86400, public=True)
def manifest(request: HttpRequest) -> JsonResponse:
    data = {
        "name": "Crecenta: finanzas personales y de tu negocio",
        "short_name": "Crecenta",
        "description": "Organiza tu dinero, conoce cuánto puedes gastar y cuánto ganas.",
        "lang": "es-DO",
        "dir": "ltr",
        "start_url": "/?origen=pwa",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#f8fafb",
        "theme_color": "#10224a",
        "categories": ["finance", "productivity"],
        "icons": [
            {"src": static("icons/icon-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": static("icons/icon-512.png"), "sizes": "512x512", "type": "image/png"},
            {
                "src": static("icons/icon-maskable-512.png"),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            },
        ],
        "shortcuts": [
            {
                "name": "Registrar gasto",
                "short_name": "Gasto",
                "url": reverse("pwa:quick_entry"),
                "icons": [{"src": static("icons/icon-192.png"), "sizes": "192x192"}],
            }
        ],
    }
    response = JsonResponse(data, json_dumps_params={"ensure_ascii": False})
    response["Content-Type"] = "application/manifest+json"
    return response


def _precache_urls() -> list[str]:
    return [
        reverse("pwa:offline"),
        reverse("pwa:offline_saved"),
        *[static(path) for path in PRECACHE_STATIC],
    ]


@require_GET
@never_cache
def service_worker(request: HttpRequest) -> HttpResponse:
    urls = _precache_urls()
    # La versión cambia sola cuando cambian los archivos (en producción llevan hash en el nombre).
    version = hashlib.sha256(("|".join(urls) + settings.APP_VERSION).encode()).hexdigest()[:12]
    body = render_to_string(
        "pwa/sw.js",
        {
            "version": version,
            "precache_json": json.dumps(urls),
            "offline_url": reverse("pwa:offline"),
            "saved_url": reverse("pwa:offline_saved"),
        },
    )
    response = HttpResponse(body, content_type="application/javascript; charset=utf-8")
    response["Service-Worker-Allowed"] = "/"
    return response


@require_GET
def offline(request: HttpRequest) -> HttpResponse:
    return HttpResponse(render_to_string("pwa/offline.html", {"saved": False}))


@require_GET
def offline_saved(request: HttpRequest) -> HttpResponse:
    return HttpResponse(render_to_string("pwa/offline.html", {"saved": True}))


@login_required
@require_GET
def quick_entry(request: HttpRequest) -> HttpResponse:
    """Atajo del ícono instalado: abre "Registrar" en el espacio activo."""
    workspace = default_workspace(request.user, request.session.get(SESSION_KEY))
    if workspace is None:
        return redirect("workspaces:usage")
    return redirect("ledger:new", ws=workspace.pk)
