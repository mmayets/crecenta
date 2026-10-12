from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel
from apps.core.money import CURRENCY_CHOICES

from .managers import WorkspaceQuerySet, WorkspaceScopedQuerySet


def default_currency() -> str:
    return settings.DEFAULT_CURRENCY


class Workspace(TimeStampedModel):
    """Espacio financiero: personal o de negocio. Todos los datos de dominio cuelgan de uno."""

    class Kind(models.TextChoices):
        PERSONAL = "personal", "Personal"
        BUSINESS = "business", "Negocio"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="propietario",
        on_delete=models.CASCADE,
        related_name="owned_workspaces",
    )
    kind = models.CharField("tipo", max_length=10, choices=Kind.choices)
    name = models.CharField("nombre", max_length=80)
    currency = models.CharField(
        "moneda", max_length=3, choices=CURRENCY_CHOICES, default=default_currency
    )

    objects = WorkspaceQuerySet.as_manager()

    class Meta:
        verbose_name = "espacio financiero"
        verbose_name_plural = "espacios financieros"
        constraints = [
            # Un usuario tiene como máximo un espacio personal; puede tener varios de negocio.
            models.UniqueConstraint(
                fields=["owner"],
                condition=Q(kind="personal"),
                name="un_espacio_personal_por_usuario",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def is_personal(self) -> bool:
        return self.kind == self.Kind.PERSONAL

    @property
    def is_business(self) -> bool:
        return self.kind == self.Kind.BUSINESS


class Membership(TimeStampedModel):
    class Role(models.TextChoices):
        OWNER = "owner", "Propietario"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField("rol", max_length=10, choices=Role.choices, default=Role.OWNER)

    objects = WorkspaceScopedQuerySet.as_manager()

    class Meta:
        verbose_name = "membresía"
        verbose_name_plural = "membresías"
        constraints = [
            models.UniqueConstraint(fields=["user", "workspace"], name="membresia_unica"),
        ]

    def __str__(self) -> str:
        return f"{self.user} · {self.workspace}"


class WorkspaceScopedModel(TimeStampedModel):
    """Base abstracta de los modelos de dominio: pertenecen a un único espacio."""

    workspace = models.ForeignKey(
        Workspace, verbose_name="espacio", on_delete=models.CASCADE, related_name="+"
    )

    objects = WorkspaceScopedQuerySet.as_manager()

    class Meta:
        abstract = True
