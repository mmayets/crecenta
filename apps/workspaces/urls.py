from django.urls import path

from . import team_views, views

app_name = "workspaces"

urlpatterns = [
    path("espacios/", views.selector, name="selector"),
    path("espacios/nuevo/", views.usage, name="usage"),
    path("invitacion/<str:token>/", team_views.accept, name="accept_invitation"),
]
