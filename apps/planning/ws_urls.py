from django.urls import path

from . import views

app_name = "planning"

urlpatterns = [
    path("plan/", views.index, name="index"),
    path("plan/generar/", views.generate, name="generate"),
    path("plan/comparar/", views.compare, name="compare"),
    path("plan/<uuid:plan_id>/", views.detail, name="detail"),
    path("plan/<uuid:plan_id>/aceptar/", views.accept, name="accept"),
    path("plan/<uuid:plan_id>/descartar/", views.discard, name="discard"),
    path("plan/<uuid:plan_id>/editar/", views.edit, name="edit"),
    path("plan/<uuid:plan_id>/aplicar/", views.apply_alternative, name="apply"),
]
