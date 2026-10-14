from django.urls import path

from . import views

app_name = "panel"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("comportamiento/", views.behavior, name="behavior"),
    path("finanzas/", views.finances, name="finances"),
    path("usuarios/", views.users, name="users"),
    path("usuarios/<uuid:user_id>/", views.user_detail, name="user_detail"),
    path("auditoria/", views.audit, name="audit"),
    path("notificaciones/", views.notifications, name="notifications"),
    path("parametros/", views.parameters, name="parameters"),
    path("parametros/nuevo/", views.parameter_edit, name="parameter_new"),
    path("parametros/<uuid:parameter_id>/", views.parameter_edit, name="parameter_edit"),
    path(
        "parametros/<uuid:parameter_id>/eliminar/",
        views.parameter_delete,
        name="parameter_delete",
    ),
]
