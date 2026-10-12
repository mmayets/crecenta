from django.db import connection
from django.http import HttpRequest, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


@never_cache
@require_GET
def health(request: HttpRequest) -> JsonResponse:
    """Verificación para el orquestador de contenedores."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return JsonResponse({"estado": "ok"})
