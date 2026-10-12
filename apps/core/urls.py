from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("salud/", views.health, name="health"),
]
