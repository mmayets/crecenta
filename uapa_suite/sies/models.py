from django.conf import settings
from django.db import models


class Seccion(models.Model):
    class Calificaciones(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        EN_CURSO = "en_curso", "En curso"
        APROBADO = "aprobado", "Aprobado"

    docente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="secciones")
    trimestre = models.CharField(max_length=60, help_text="p. ej. «noviembre – enero 2027».")
    activo = models.BooleanField("trimestre actual", default=True)
    codigo = models.CharField("código", max_length=20)
    asignatura = models.CharField(max_length=120)
    numero = models.PositiveSmallIntegerField("sección")
    inscritos = models.PositiveSmallIntegerField(default=0)
    nuevos = models.PositiveSmallIntegerField("estudiantes nuevos", default=0)
    asistencia = models.PositiveSmallIntegerField("asistencia promedio (%)", default=0)
    calificaciones = models.CharField(max_length=20, choices=Calificaciones.choices, default=Calificaciones.PENDIENTE)

    class Meta:
        ordering = ["id"]  # orden en que se asignaron
        verbose_name = "sección"
        verbose_name_plural = "secciones"

    def __str__(self) -> str:
        return f"{self.codigo} {self.asignatura} Sec. {self.numero:02d}"
