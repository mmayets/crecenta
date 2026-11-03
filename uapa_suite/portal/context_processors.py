from .models import Aplicacion


def aplicaciones_de(usuario):
    """Aplicaciones visibles para el usuario (todas si su perfil no restringe)."""
    qs = Aplicacion.objects.all()
    perfil = getattr(usuario, "perfil", None)
    if perfil is not None and perfil.aplicaciones.exists():
        qs = perfil.aplicaciones.all()
    return qs


def suite(request):
    usuario = request.user
    if not usuario.is_authenticated:
        return {}
    perfil = getattr(usuario, "perfil", None)
    nombre = usuario.get_full_name() or usuario.get_username()
    iniciales = "".join(p[0] for p in nombre.split()[:2]).upper()
    return {
        "suite_apps": aplicaciones_de(usuario),
        "suite_usuario": {
            "nombre": nombre,
            "iniciales": iniciales,
            "rol": perfil.rol if perfil else "Colaborador",
        },
        "suite_no_leidas": usuario.notificaciones.filter(leida=False).count(),
        "suite_notificaciones": usuario.notificaciones.select_related("aplicacion")[:5],
    }
