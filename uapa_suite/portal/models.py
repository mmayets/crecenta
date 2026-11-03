from django.conf import settings
from django.db import models
from django.urls import NoReverseMatch, reverse
from django.utils import timezone


class Aplicacion(models.Model):
    """Una aplicación de la suite (PopIn, Tu Espacio GTH, Presupuesto…)."""

    class Color(models.TextChoices):
        POPIN = "popin", "Naranja (PopIn)"
        GTH = "gth", "Verde (GTH)"
        PRESUPUESTO = "presupuesto", "Azul (Presupuesto)"
        SIES = "sies", "Morado (SIES)"
        DOCS = "docs", "Ocre (Documentos)"
        HELP = "help", "Rojo (Mesa de ayuda)"

    nombre = models.CharField(max_length=80)
    slug = models.SlugField(unique=True)
    descripcion = models.CharField("descripción", max_length=160)
    icono = models.CharField(
        max_length=60,
        help_text="Nombre de Bootstrap Icons sin el prefijo «bi-», p. ej. «chat-square-quote».",
    )
    color = models.CharField(max_length=20, choices=Color.choices, default=Color.POPIN)
    url = models.URLField(
        blank=True,
        help_text="Dirección externa. Déjela vacía para usar el módulo interno con el mismo slug (popin, gth, presupuesto, sies).",
    )
    disponible = models.BooleanField(default=True, help_text="Desmarque para mostrarla como «Próximamente».")
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["orden", "nombre"]
        verbose_name = "aplicación"
        verbose_name_plural = "aplicaciones"

    def __str__(self) -> str:
        return self.nombre

    @property
    def es_externa(self) -> bool:
        return bool(self.url)

    @property
    def enlace(self) -> str:
        """URL externa si se configuró; si no, el módulo interno con el mismo slug (p. ej. /gth/)."""
        if self.url:
            return self.url
        try:
            return reverse(f"{self.slug}:inicio")
        except NoReverseMatch:
            return ""


class Aviso(models.Model):
    """Aviso institucional destacado en la portada."""

    etiqueta = models.CharField(max_length=40, default="Aviso institucional")
    titulo = models.CharField("título", max_length=160)
    texto = models.CharField(max_length=300, blank=True)
    texto_boton = models.CharField("texto del botón", max_length=60, blank=True)
    aplicacion = models.ForeignKey(
        Aplicacion, on_delete=models.SET_NULL, null=True, blank=True, related_name="avisos",
        help_text="Si se indica, el botón lleva a esta aplicación.",
    )
    url = models.URLField(blank=True, help_text="Dirección del botón si no hay aplicación.")
    activo = models.BooleanField(default=True)
    inicio = models.DateTimeField(default=timezone.now)
    fin = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-inicio"]
        verbose_name_plural = "avisos"

    def __str__(self) -> str:
        return self.titulo

    @property
    def enlace(self) -> str:
        if self.aplicacion and self.aplicacion.enlace:
            return self.aplicacion.enlace
        return self.url

    @classmethod
    def vigente(cls):
        ahora = timezone.now()
        return (
            cls.objects.filter(activo=True, inicio__lte=ahora)
            .filter(models.Q(fin__isnull=True) | models.Q(fin__gte=ahora))
            .select_related("aplicacion")
            .first()
        )


class Perfil(models.Model):
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="perfil")
    rol = models.CharField(max_length=60, default="Colaborador")
    aplicaciones = models.ManyToManyField(
        Aplicacion, blank=True, related_name="perfiles",
        help_text="Vacío: el usuario ve todas las aplicaciones.",
    )

    class Meta:
        verbose_name_plural = "perfiles"

    def __str__(self) -> str:
        return f"{self.usuario} · {self.rol}"


class Pendiente(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="pendientes")
    aplicacion = models.ForeignKey(Aplicacion, on_delete=models.CASCADE, related_name="pendientes")
    titulo = models.CharField("título", max_length=160)
    url = models.CharField(max_length=300, blank=True, help_text="Ruta interna (/presupuesto/solicitudes/) o URL completa.")
    completado = models.BooleanField(default=False)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["completado", "-creado"]

    def __str__(self) -> str:
        return self.titulo

    @property
    def enlace(self) -> str:
        return self.url or self.aplicacion.enlace


class EventoAgenda(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="eventos")
    titulo = models.CharField("título", max_length=120)
    inicio = models.DateTimeField()
    lugar = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["inicio"]
        verbose_name = "evento de agenda"
        verbose_name_plural = "agenda"

    def __str__(self) -> str:
        return self.titulo


class Notificacion(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notificaciones")
    aplicacion = models.ForeignKey(Aplicacion, on_delete=models.SET_NULL, null=True, blank=True)
    texto = models.CharField(max_length=200)
    leida = models.BooleanField("leída", default=False)
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creada"]
        verbose_name = "notificación"
        verbose_name_plural = "notificaciones"

    def __str__(self) -> str:
        return self.texto
