from django.urls import path

from . import views

app_name = "popin"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("noticias/", views.noticias, name="noticias"),
    path("eventos/", views.eventos, name="eventos"),
    path("encuestas/", views.encuestas, name="encuestas"),
    path("guardados/", views.guardados, name="guardados"),
    path("nuevo/", views.nuevo, name="nuevo"),
    path("c/<int:pk>/", views.detalle, name="detalle"),
    path("c/<int:pk>/me-gusta/", views.me_gusta, name="me_gusta"),
    path("c/<int:pk>/guardar/", views.guardar, name="guardar"),
]
