from django.contrib import admin

from .models import Aplicacion, Aviso, EventoAgenda, Notificacion, Pendiente, Perfil


@admin.register(Aplicacion)
class AplicacionAdmin(admin.ModelAdmin):
    list_display = ("nombre", "descripcion", "color", "disponible", "orden")
    list_editable = ("disponible", "orden")
    prepopulated_fields = {"slug": ("nombre",)}


@admin.register(Aviso)
class AvisoAdmin(admin.ModelAdmin):
    list_display = ("titulo", "activo", "inicio", "fin")
    list_filter = ("activo",)


@admin.register(Perfil)
class PerfilAdmin(admin.ModelAdmin):
    list_display = ("usuario", "rol")
    filter_horizontal = ("aplicaciones",)


@admin.register(Pendiente)
class PendienteAdmin(admin.ModelAdmin):
    list_display = ("titulo", "usuario", "aplicacion", "completado", "creado")
    list_filter = ("completado", "aplicacion")
    search_fields = ("titulo",)


@admin.register(EventoAgenda)
class EventoAgendaAdmin(admin.ModelAdmin):
    list_display = ("titulo", "usuario", "inicio", "lugar")
    date_hierarchy = "inicio"


@admin.register(Notificacion)
class NotificacionAdmin(admin.ModelAdmin):
    list_display = ("texto", "usuario", "aplicacion", "leida", "creada")
    list_filter = ("leida",)
