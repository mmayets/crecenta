from django.urls import path

from . import views

app_name = "onboarding"

urlpatterns = [
    path("bienvenida/", views.index, name="index"),
    path("bienvenida/listo/", views.done, name="done"),
    path("bienvenida/conversacion/", views.conversation, name="conversation"),
    path("bienvenida/conversacion/confirmar/", views.confirm, name="confirm"),
    path("bienvenida/voz/", views.voice, name="voice"),
    path("bienvenida/<slug:step>/", views.step, name="step"),
]
