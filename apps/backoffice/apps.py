from django.apps import AppConfig


class BackofficeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.backoffice"
    verbose_name = "Administración y auditoría"

    def ready(self) -> None:
        from . import signals  # noqa: F401
