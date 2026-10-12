from django.urls import path

from . import views

app_name = "ledger"

urlpatterns = [
    path("movimientos/", views.movements, name="movements"),
    path("movimientos/nuevo/", views.new, name="new"),
    path("movimientos/texto/", views.from_text, name="from_text"),
    path("movimientos/transferir/", views.transfer, name="transfer"),
    path("movimientos/avisos/", views.warnings, name="warnings"),
    path("movimientos/sync/", views.sync, name="sync"),
    path("movimientos/<uuid:tx_id>/eliminar/", views.delete, name="delete"),
    path("ajustes/cuentas/", views.accounts, name="accounts"),
    path("ajustes/cuentas/<uuid:account_id>/", views.accounts, name="account_edit"),
    path("ajustes/categorias/", views.categories, name="categories"),
    path("ajustes/categorias/<uuid:category_id>/", views.categories, name="category_edit"),
]
