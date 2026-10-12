from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("configuracion/", views.settings_view, name="settings"),
    path("exportar/", views.export_view, name="export"),
    path("eliminar/", views.delete_view, name="delete"),
]
