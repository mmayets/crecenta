"""Ventas registradas sin conexión (docs/fase4.md §5).

El teléfono guarda los campos del formulario de venta con su client_uuid y los envía al reconectar.
Se validan con el mismo formulario de la pantalla y se registran con `register_sale` (no duplica).
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_POST

from apps.business.forms import SaleForm
from apps.business.services.sales import register_sale
from apps.core.ratelimit import hit
from apps.ledger.choices import TxSource
from apps.workspaces.mixins import workspace_required
from apps.workspaces.models import Workspace
from apps.workspaces.permissions import VENDER

MAX_BATCH = 50


def _sync_one(workspace: Workspace, user: Any, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or not isinstance(raw.get("form"), dict):
        return {"client_uuid": "", "estado": "error", "errores": {"": ["Formato"]}}
    fields = {str(k): str(v) for k, v in raw["form"].items() if not isinstance(v, (dict, list))}
    fields["client_uuid"] = str(raw.get("client_uuid", ""))
    form = SaleForm(fields, workspace=workspace)
    if not form.is_valid():
        errors = {name: [str(m) for m in messages] for name, messages in form.errors.items()}
        return {"client_uuid": fields["client_uuid"], "estado": "error", "errores": errors}
    data = dataclasses.replace(form.to_sale_data(), source=TxSource.OFFLINE)
    try:
        sale, created = register_sale(workspace, user, data)
    except ValidationError as exc:
        return {
            "client_uuid": fields["client_uuid"],
            "estado": "error",
            "errores": {"": exc.messages},
        }
    return {
        "client_uuid": fields["client_uuid"],
        "estado": "creado" if created else "existente",
        "id": str(sale.pk),
    }


@workspace_required(kind="business", perm=VENDER)
@require_POST
def sales_sync(request: HttpRequest, workspace: Workspace) -> JsonResponse:
    """Recibe {"items": [{"client_uuid": …, "form": {campos del formulario}}]}."""
    if not hit(f"sync:{request.user.pk}", settings.SYNC_RATE_LIMITS):
        return JsonResponse({"error": "Demasiados envíos. Intenta en un momento."}, status=429)
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "JSON inválido"}, status=400)
    items = body.get("items") if isinstance(body, dict) else None
    if not isinstance(items, list):
        return JsonResponse({"error": "Se espera {'items': [...]}"}, status=400)
    if len(items) > MAX_BATCH:
        return JsonResponse({"error": f"Máximo {MAX_BATCH} ventas por envío."}, status=400)
    return JsonResponse({"resultados": [_sync_one(workspace, request.user, i) for i in items]})
