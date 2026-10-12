from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


@login_required
def home(request: HttpRequest) -> HttpResponse:
    # Provisional: en el paso 2 redirige al espacio activo del usuario.
    return render(request, "core/home.html")


@never_cache
@require_GET
def health(request: HttpRequest) -> JsonResponse:
    """Verificación para el orquestador de contenedores."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return JsonResponse({"estado": "ok"})
