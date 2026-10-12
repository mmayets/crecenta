from django.http import HttpRequest

from .models import Workspace


def workspaces(request: HttpRequest) -> dict:
    """Espacio activo y lista para el selector persona/negocio."""
    if not request.user.is_authenticated:
        return {}
    return {
        "current_workspace": getattr(request, "workspace", None),
        "user_workspaces": Workspace.objects.for_user(request.user).personal_first(),
    }
