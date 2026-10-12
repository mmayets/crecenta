from django.urls import path

from . import views

app_name = "ledger"

urlpatterns = [
    path("movimientos/sync/", views.sync, name="sync"),
]
