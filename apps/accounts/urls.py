from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("configuracion/", views.settings_view, name="settings"),
    path("exportar/", views.export_view, name="export"),
    path("eliminar/", views.delete_view, name="delete"),
    path("notificaciones/suscribir/", views.push_subscribe, name="push_subscribe"),
    path("notificaciones/cancelar/", views.push_unsubscribe, name="push_unsubscribe"),
    path("notificaciones/prueba/", views.push_test, name="push_test"),
]
