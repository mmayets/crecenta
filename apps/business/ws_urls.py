from django.urls import path

from . import inventory_views as inv
from . import views

app_name = "business"

urlpatterns = [
    path("ventas/", views.sales, name="sales"),
    path("ventas/nueva/", views.sale_new, name="sale_new"),
    path("ventas/<uuid:sale_id>/", views.sale_detail, name="sale_detail"),
    path("ventas/<uuid:sale_id>/anular/", views.sale_delete, name="sale_delete"),
    path("productos/", views.products, name="products"),
    path("productos/nuevo/", views.product_edit, name="product_new"),
    path("productos/<uuid:product_id>/", views.product_edit, name="product_edit"),
    path("precios/", views.pricing, name="pricing"),
    path("por-cobrar/", views.receivables, name="receivables"),
    path("por-cobrar/<uuid:debt_id>/cobrar/", views.collect, name="collect"),
    path("por-pagar/", views.payables, name="payables"),
    path("por-pagar/<uuid:debt_id>/pagar/", views.pay, name="pay"),
    path("propietario/", views.owner, name="owner"),
    path("propietario/aviso/", views.owner_check, name="owner_check"),
    # Fase 3
    path("ventas/<uuid:sale_id>/editar/", inv.sale_edit, name="sale_edit"),
    path("inventario/", inv.inventory, name="inventory"),
    path("inventario/<uuid:product_id>/", inv.stock_product, name="stock_product"),
    path(
        "inventario/movimientos/<uuid:movement_id>/eliminar/",
        inv.movement_delete,
        name="movement_delete",
    ),
    path("compras/", inv.purchases, name="purchases"),
    path("compras/nueva/", inv.purchase_new, name="purchase_new"),
    path("compras/<uuid:purchase_id>/", inv.purchase_detail, name="purchase_detail"),
    path("compras/<uuid:purchase_id>/anular/", inv.purchase_delete, name="purchase_delete"),
    path("reportes/", inv.reports, name="reports"),
    path("reportes/resultados.csv", inv.reports_csv, name="reports_csv"),
]
