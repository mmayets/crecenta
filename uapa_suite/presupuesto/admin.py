from django.contrib import admin

from .models import Departamento, SolicitudCompra


@admin.register(Departamento)
class DepartamentoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "anio", "aprobado", "ejecutado", "comprometido", "orden")
    list_filter = ("anio",)


@admin.register(SolicitudCompra)
class SolicitudCompraAdmin(admin.ModelAdmin):
    list_display = ("numero", "descripcion", "departamento", "monto", "estado", "creada")
    list_filter = ("estado", "departamento__anio")
    search_fields = ("descripcion",)
