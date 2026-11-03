from datetime import date

from django.conf import settings
from django.db import models


def anio_actual() -> int:
    return date.today().year


class FichaColaborador(models.Model):
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ficha_gth")
    fecha_ingreso = models.DateField()
    dias_vacaciones = models.PositiveSmallIntegerField("días de vacaciones disponibles", default=0)
    meta_horas_capacitacion = models.PositiveSmallIntegerField("meta anual de horas de capacitación", default=40)

    class Meta:
        verbose_name = "ficha de colaborador"
        verbose_name_plural = "fichas de colaboradores"

    def __str__(self) -> str:
        return str(self.usuario)

    def antiguedad_anios(self, hoy: date | None = None) -> int:
        hoy = hoy or date.today()
        anios = hoy.year - self.fecha_ingreso.year
        if (hoy.month, hoy.day) < (self.fecha_ingreso.month, self.fecha_ingreso.day):
            anios -= 1
        return max(anios, 0)


class Estado(models.TextChoices):
    PENDIENTE = "pendiente", "Pendiente"
    APROBADO = "aprobado", "Aprobado"
    RECHAZADO = "rechazado", "Rechazado"


class Solicitud(models.Model):
    class Tipo(models.TextChoices):
        VACACIONES = "vacaciones", "Vacaciones"
        CARTA = "carta", "Carta de trabajo"
        PERMISO = "permiso", "Permiso"
        HORARIO = "horario", "Cambio de horario"
        OTRO = "otro", "Otro"

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="solicitudes_gth")
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    descripcion = models.CharField("descripción", max_length=160)
    fecha_inicio = models.DateField(null=True, blank=True)
    fecha_fin = models.DateField(null=True, blank=True)
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.PENDIENTE)
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creada"]
        verbose_name = "solicitud"
        verbose_name_plural = "solicitudes"

    def __str__(self) -> str:
        return self.descripcion


class Capacitacion(models.Model):
    nombre = models.CharField(max_length=120)
    horas = models.PositiveSmallIntegerField(default=8)

    class Meta:
        ordering = ["nombre"]
        verbose_name = "capacitación"
        verbose_name_plural = "capacitaciones"

    def __str__(self) -> str:
        return self.nombre


class Inscripcion(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="capacitaciones")
    capacitacion = models.ForeignKey(Capacitacion, on_delete=models.CASCADE, related_name="inscripciones")
    progreso = models.PositiveSmallIntegerField(default=0, help_text="Porcentaje 0–100.")
    recomendada = models.BooleanField(default=True)
    anio = models.PositiveSmallIntegerField("año", default=anio_actual)

    class Meta:
        unique_together = [("usuario", "capacitacion", "anio")]
        verbose_name = "inscripción"
        verbose_name_plural = "inscripciones"

    def __str__(self) -> str:
        return f"{self.usuario} · {self.capacitacion}"


class Evaluacion(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="evaluaciones")
    anio = models.PositiveSmallIntegerField("año")
    vence = models.DateField()
    completada = models.BooleanField(default=False)

    class Meta:
        ordering = ["-anio"]
        unique_together = [("usuario", "anio")]
        verbose_name = "evaluación de desempeño"
        verbose_name_plural = "evaluaciones de desempeño"

    def __str__(self) -> str:
        return f"{self.usuario} · {self.anio}"
