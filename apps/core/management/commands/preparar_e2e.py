"""Crea (o recrea) la persona de las pruebas de punta a punta y devuelve sus datos en JSON."""

import json

from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.workspaces.services.workspaces import create_workspaces_for_usage

EMAIL = "e2e@crecenta.test"
PASSWORD = "Prueba-E2E-2026"  # noqa: S105 - usuario desechable de pruebas locales


class Command(BaseCommand):
    help = "Prepara el usuario de las pruebas E2E (solo para entornos de desarrollo)."

    def handle(self, *args, **options) -> None:
        User.objects.filter(email=EMAIL).delete()
        user = User.objects.create_user(EMAIL, PASSWORD, first_name="Prueba")
        (workspace,) = create_workspaces_for_usage(user, "persona")
        self.stdout.write(
            json.dumps({"email": EMAIL, "password": PASSWORD, "ws": str(workspace.pk)})
        )
