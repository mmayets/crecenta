import json

from django.core.exceptions import ValidationError
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_POST

from apps.workspaces.mixins import workspace_required
from apps.workspaces.models import Workspace

from .services.sync import sync_batch


@workspace_required
@require_POST
def sync(request: HttpRequest, workspace: Workspace) -> JsonResponse:
    """Recibe movimientos registrados sin conexión: {"items": [...]}. Idempotente por client_uuid.

    Responde 200 con el resultado de cada elemento (creado / existente / error) para que el
    dispositivo elimine de su cola los que ya quedaron guardados.
    """
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "JSON inválido"}, status=400)
    items = body.get("items") if isinstance(body, dict) else None
    if not isinstance(items, list):
        return JsonResponse({"error": "Se espera {'items': [...]}"}, status=400)
    try:
        results = sync_batch(workspace, request.user, items)
    except ValidationError as exc:
        return JsonResponse({"error": exc.messages[0]}, status=400)
    return JsonResponse({"resultados": results})
