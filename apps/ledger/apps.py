from django.apps import AppConfig


class LedgerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ledger"
    verbose_name = "Movimientos"

    def ready(self) -> None:
        from . import signals  # noqa: F401
