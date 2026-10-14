"""Registro de auditoría. `record` nunca interrumpe la petición: si falla, lo anota en el log."""

from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from django.http import HttpRequest

from apps.backoffice.models import AuditEvent

logger = logging.getLogger(__name__)
Kind = AuditEvent.Kind

# Descripción legible de las acciones más comunes (vista → texto). El resto se describe con su
# nombre de vista, así ninguna acción queda sin registrar.
ACTION_LABELS = {
    "ledger:new": "Registró un movimiento",
    "ledger:from_text": "Interpretó un movimiento escrito",
    "ledger:transfer": "Registró una transferencia",
    "ledger:delete": "Eliminó un movimiento",
    "ledger:sync": "Sincronizó movimientos guardados sin conexión",
    "ledger:accounts": "Guardó una cuenta",
    "ledger:account_edit": "Editó una cuenta",
    "ledger:categories": "Guardó una categoría",
    "ledger:category_edit": "Editó una categoría",
    "ledger:sophia": "Conversó con Sophia para registrar",
    "ledger:sophia_save": "Guardó un movimiento preparado por Sophia",
    "ledger:sophia_restart": "Reinició la conversación con Sophia",
    "business:sale_new": "Registró una venta",
    "business:sales_sync": "Sincronizó ventas guardadas sin conexión",
    "business:sale_delete": "Anuló una venta",
    "business:sale_edit": "Editó una venta",
    "business:product_new": "Creó un producto",
    "business:product_edit": "Editó un producto",
    "business:collect": "Registró un cobro",
    "business:pay": "Registró un pago a proveedor",
    "business:owner": "Registró un retiro o aporte",
    "business:purchase_new": "Registró una compra",
    "business:purchase_delete": "Anuló una compra",
    "business:movement_delete": "Eliminó un movimiento de inventario",
    "business:stock_product": "Ajustó el inventario",
    "business:reports_csv": "Descargó el informe de resultados",
    "business:dgii_csv": "Descargó un archivo de apoyo DGII",
    "planning:generate": "Pidió un plan",
    "planning:accept": "Aceptó un plan",
    "planning:discard": "Descartó un plan",
    "planning:edit": "Editó un plan",
    "planning:apply": "Aplicó una alternativa del plan",
    "alerts:dismiss": "Descartó una alerta",
    "alerts:resolve": "Resolvió una alerta",
    "alerts:rules": "Cambió sus reglas de alertas",
    "receipts:index": "Subió un comprobante",
    "receipts:detail": "Revisó un comprobante",
    "onboarding:step": "Respondió un paso de su perfil",
    "onboarding:conversation": "Describió su situación para la IA",
    "onboarding:confirm": "Confirmó los datos extraídos",
    "onboarding:done": "Terminó su perfil y pidió el plan",
    "onboarding:ask": "Hizo una pregunta a Sophia",
    "onboarding:voice": "Dictó una nota de voz",
    "espacio:team": "Invitó a alguien al equipo",
    "espacio:member_role": "Cambió el rol de un miembro",
    "espacio:member_remove": "Quitó a un miembro del equipo",
    "espacio:invitation_revoke": "Anuló una invitación",
    "workspaces:usage": "Creó un espacio con el formulario",
    "workspaces:accept_invitation": "Aceptó una invitación",
    "asistente:chat": "Conversó con Sophia para crear un espacio",
    "asistente:create": "Creó un espacio con Sophia (chat)",
    "asistente:first_space_step": "Respondió un paso del primer espacio",
    "asistente:first_space_create": "Creó un espacio con Sophia (tarjetas)",
    "asistente:enable_ai": "Activó el uso de IA desde Sophia",
    "accounts:settings": "Cambió su configuración",
    "accounts:delete": "Eliminó su cuenta",
    "accounts:export": "Descargó sus datos",
}

# Sección de la app según el espacio de nombres de la vista (para las estadísticas de uso).
SECTIONS = {
    "espacio": "Panel y ajustes",
    "ledger": "Movimientos",
    "business": "Negocio",
    "planning": "Plan",
    "alerts": "Alertas",
    "receipts": "Comprobantes",
    "onboarding": "Perfil y Sophia",
    "asistente": "Crear espacios",
    "workspaces": "Espacios",
    "accounts": "Cuenta",
    "panel": "Administración",
    "admin": "Admin de Django",
}


def section_for(action: str) -> str:
    return SECTIONS.get(action.split(":", 1)[0], "Otras") if ":" in action else "Acceso"


def describe(action: str, kind: str) -> str:
    if action in ACTION_LABELS:
        return ACTION_LABELS[action]
    prefix = "Visitó" if kind == Kind.VISITA else "Acción en"
    return f"{prefix} {action or 'una página'}"


def client_ip(request: HttpRequest) -> str | None:
    return request.META.get("REMOTE_ADDR") or None


def record(
    *,
    kind: str,
    action: str,
    description: str = "",
    request: HttpRequest | None = None,
    user: Any = None,
    user_email: str = "",
    status: int | None = None,
    workspace_id: Any = None,
    duration_ms: int | None = None,
    data: dict[str, Any] | None = None,
) -> AuditEvent | None:
    try:
        request_user = getattr(request, "user", None)
        if user is None and request_user is not None and request_user.is_authenticated:
            user = request_user
        # Punto de guardado propio: si el registro falla, no arrastra la transacción de la acción.
        with transaction.atomic():
            return _create(request, user, user_email, kind, action, description, status,
                           workspace_id, duration_ms, data)  # fmt: skip
    except Exception:  # la auditoría nunca debe romper la acción del usuario
        logger.exception("No se pudo registrar el evento de auditoría %s", action)
        return None


def _create(request, user, user_email, kind, action, description, status, workspace_id,
            duration_ms, data) -> AuditEvent:  # fmt: skip
    meta = request.META if request is not None else {}
    return AuditEvent.objects.create(
        user=user if getattr(user, "pk", None) else None,
        user_email=(getattr(user, "email", "") or user_email)[:254],
        kind=kind,
        action=action[:80],
        description=(description or describe(action, kind))[:200],
        method=(getattr(request, "method", "") or "")[:8],
        path=(getattr(request, "path", "") or "")[:300],
        status=status,
        workspace_id=workspace_id,
        ip=meta.get("REMOTE_ADDR") or None,
        user_agent=meta.get("HTTP_USER_AGENT", "")[:200],
        duration_ms=duration_ms,
        data=data or {},
    )


def anonymize(user: Any) -> int:
    """Al eliminar una cuenta: los eventos quedan, pero sin datos que identifiquen a la persona."""
    return AuditEvent.objects.filter(user=user).update(
        user=None, user_email="(cuenta eliminada)", ip=None, user_agent=""
    )
