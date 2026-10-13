from django.http import HttpRequest

from .models import Workspace
from .permissions import perms_for


def workspaces(request: HttpRequest) -> dict:
    """Espacio activo, lista para el selector y alertas nuevas (insignia del menú)."""
    if not request.user.is_authenticated:
        return {}
    current = getattr(request, "workspace", None)
    role = getattr(request, "workspace_role", None)
    perms = perms_for(role)
    new_alerts = 0
    if current is not None and "finanzas" in perms:
        from apps.alerts.models import Alert

        new_alerts = Alert.objects.for_workspace(current).filter(status=Alert.Status.NUEVA).count()
    return {
        "current_workspace": current,
        "user_workspaces": Workspace.objects.for_user(request.user).personal_first(),
        "new_alerts": new_alerts,
        # Permisos en el espacio activo, para mostrar solo lo que el rol puede usar.
        "ws_role": role,
        "ws_perms": perms,
        "can_finanzas": "finanzas" in perms,
        "can_propietario": "propietario" in perms,
    }
