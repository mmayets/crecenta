from django.apps import AppConfig


class AIConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ai"
    verbose_name = "Inteligencia artificial"

    def ready(self) -> None:
        from .providers import fake_responders  # noqa: F401
