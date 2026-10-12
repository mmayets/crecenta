from django.http import HttpRequest

from .models import Workspace


def workspaces(request: HttpRequest) -> dict:
    """Espacio activo, lista para el selector y alertas nuevas (insignia del menú)."""
    if not request.user.is_authenticated:
        return {}
    current = getattr(request, "workspace", None)
    new_alerts = 0
    if current is not None:
        from apps.alerts.models import Alert

        new_alerts = Alert.objects.for_workspace(current).filter(status=Alert.Status.NUEVA).count()
    return {
        "current_workspace": current,
        "user_workspaces": Workspace.objects.for_user(request.user).personal_first(),
        "new_alerts": new_alerts,
    }
