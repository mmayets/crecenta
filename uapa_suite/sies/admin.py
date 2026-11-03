from django.contrib import admin

from .models import Seccion


@admin.register(Seccion)
class SeccionAdmin(admin.ModelAdmin):
    list_display = ("codigo", "asignatura", "numero", "docente", "trimestre", "inscritos", "calificaciones", "activo")
    list_filter = ("activo", "calificaciones", "trimestre")
    search_fields = ("codigo", "asignatura")
