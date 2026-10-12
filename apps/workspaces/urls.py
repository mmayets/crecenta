from django.urls import path

from . import views

app_name = "workspaces"

urlpatterns = [
    path("espacios/", views.selector, name="selector"),
    path("espacios/nuevo/", views.usage, name="usage"),
]
