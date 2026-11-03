from django.contrib import admin

from .models import Comentario, Comunicado


class ComentarioInline(admin.TabularInline):
    model = Comentario
    extra = 0


@admin.register(Comunicado)
class ComunicadoAdmin(admin.ModelAdmin):
    list_display = ("titulo", "tipo", "area", "publicado")
    list_filter = ("tipo", "area")
    search_fields = ("titulo", "resumen")
    date_hierarchy = "publicado"
    exclude = ("me_gusta", "leido_por", "guardado_por")
    inlines = [ComentarioInline]
