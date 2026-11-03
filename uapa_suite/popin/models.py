from django.conf import settings
from django.db import models
from django.utils import timezone


class Comunicado(models.Model):
    class Tipo(models.TextChoices):
        COMUNICADO = "comunicado", "Comunicado"
        NOTICIA = "noticia", "Noticia"
        EVENTO = "evento", "Evento"
        ENCUESTA = "encuesta", "Encuesta"

    tipo = models.CharField(max_length=20, choices=Tipo.choices, default=Tipo.COMUNICADO)
    titulo = models.CharField("título", max_length=160)
    area = models.CharField("área", max_length=60, help_text="Quién lo emite, p. ej. Rectoría, TIC.")
    resumen = models.CharField(max_length=300)
    cuerpo = models.TextField(blank=True)
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    publicado = models.DateTimeField(default=timezone.now)
    me_gusta = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="comunicados_gustados")
    leido_por = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="comunicados_leidos")
    guardado_por = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="comunicados_guardados")

    class Meta:
        ordering = ["-publicado"]
        verbose_name_plural = "comunicados"

    def __str__(self) -> str:
        return self.titulo


class Comentario(models.Model):
    comunicado = models.ForeignKey(Comunicado, on_delete=models.CASCADE, related_name="comentarios")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    texto = models.TextField()
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["creado"]
        verbose_name_plural = "comentarios"

    def __str__(self) -> str:
        return self.texto[:40]
