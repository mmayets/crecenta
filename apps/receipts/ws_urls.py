from django.urls import path

from . import views

app_name = "receipts"

urlpatterns = [
    path("comprobantes/", views.index, name="index"),
    path("comprobantes/qr/", views.scan_qr, name="scan_qr"),
    path("comprobantes/<uuid:receipt_id>/", views.detail, name="detail"),
    path("comprobantes/<uuid:receipt_id>/archivo/", views.file, name="file"),
    path("comprobantes/<uuid:receipt_id>/vincular/", views.link, name="link"),
    path("comprobantes/<uuid:receipt_id>/descartar/", views.discard, name="discard"),
    path("comprobantes/<uuid:receipt_id>/reintentar/", views.retry, name="retry"),
]
