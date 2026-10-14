import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager["User"]):
    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra) -> "User":
        if not email:
            raise ValueError("El correo es obligatorio")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra) -> "User":
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email: str, password: str | None = None, **extra) -> "User":
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        if not extra["is_staff"] or not extra["is_superuser"]:
            raise ValueError("El superusuario debe tener is_staff e is_superuser")
        return self._create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    """Usuario identificado por correo electrónico."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField("correo electrónico", unique=True)
    first_name = models.CharField("nombre", max_length=150, blank=True)
    is_staff = models.BooleanField("es del equipo", default=False)
    is_active = models.BooleanField("activo", default=True)
    date_joined = models.DateTimeField("fecha de registro", default=timezone.now)

    # Consentimiento explícito para enviar datos (minimizados) al proveedor de IA.
    ai_consent = models.BooleanField("acepta uso de IA", default=False)
    ai_consent_at = models.DateTimeField("fecha de consentimiento de IA", null=True, blank=True)

    objects = UserManager()

    EMAIL_FIELD = "email"
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"

    def __str__(self) -> str:
        return self.email

    def get_full_name(self) -> str:
        return self.first_name or self.email

    def get_short_name(self) -> str:
        return self.first_name or self.email.split("@")[0]

    def set_ai_consent(self, value: bool) -> None:
        self.ai_consent = value
        self.ai_consent_at = timezone.now() if value else None
        self.save(update_fields=["ai_consent", "ai_consent_at"])


class PushSubscription(models.Model):
    """Navegador o teléfono donde la persona aceptó recibir notificaciones push."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="push_subscriptions")
    endpoint = models.URLField("dirección del servicio push", max_length=600, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    user_agent = models.CharField("navegador", max_length=200, blank=True)
    created_at = models.DateTimeField("creada", auto_now_add=True)
    last_sent_at = models.DateTimeField("último envío", null=True, blank=True)

    class Meta:
        verbose_name = "suscripción push"
        verbose_name_plural = "suscripciones push"

    def __str__(self) -> str:
        return f"{self.user} · {self.user_agent[:40]}"
