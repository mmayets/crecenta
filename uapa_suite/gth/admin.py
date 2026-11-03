from django.contrib import admin

from .models import Capacitacion, Evaluacion, FichaColaborador, Inscripcion, Solicitud


@admin.register(FichaColaborador)
class FichaAdmin(admin.ModelAdmin):
    list_display = ("usuario", "fecha_ingreso", "dias_vacaciones", "meta_horas_capacitacion")


@admin.register(Solicitud)
class SolicitudAdmin(admin.ModelAdmin):
    list_display = ("descripcion", "usuario", "tipo", "estado", "creada")
    list_filter = ("estado", "tipo")
    list_editable = ("estado",)


@admin.register(Capacitacion)
class CapacitacionAdmin(admin.ModelAdmin):
    list_display = ("nombre", "horas")


@admin.register(Inscripcion)
class InscripcionAdmin(admin.ModelAdmin):
    list_display = ("usuario", "capacitacion", "anio", "progreso", "recomendada")
    list_filter = ("anio", "recomendada")


@admin.register(Evaluacion)
class EvaluacionAdmin(admin.ModelAdmin):
    list_display = ("usuario", "anio", "vence", "completada")
    list_filter = ("anio", "completada")
