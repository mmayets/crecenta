"""Rutas bajo /e/<uuid:ws>/ (requieren membresía en el espacio)."""

from django.urls import path

from . import team_views, views

app_name = "espacio"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("ajustes/", views.settings_hub, name="settings"),
    path("equipo/", team_views.team, name="team"),
    path("equipo/<uuid:member_id>/rol/", team_views.member_role, name="member_role"),
    path("equipo/<uuid:member_id>/quitar/", team_views.member_remove, name="member_remove"),
    path(
        "equipo/invitaciones/<uuid:invitation_id>/anular/",
        team_views.invitation_revoke,
        name="invitation_revoke",
    ),
]
