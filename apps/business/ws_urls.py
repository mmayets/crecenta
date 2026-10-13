from django.urls import path

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
]
