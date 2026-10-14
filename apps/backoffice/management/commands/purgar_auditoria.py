"""Borra los eventos de auditoría más antiguos que N días (por defecto 365).

Uso: python manage.py purgar_auditoria [--dias 365] [--solo-visitas]
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.backoffice.models import AuditEvent


class Command(BaseCommand):
    help = "Borra eventos de auditoría antiguos."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--dias", type=int, default=365)
        parser.add_argument(
            "--solo-visitas", action="store_true", help="Conserva acciones, accesos y cambios"
        )

    def handle(self, *args, dias: int, solo_visitas: bool, **options) -> None:
        qs = AuditEvent.objects.filter(created_at__lt=timezone.now() - timedelta(days=dias))
        if solo_visitas:
            qs = qs.filter(kind=AuditEvent.Kind.VISITA)
        deleted, _ = qs.delete()
        self.stdout.write(self.style.SUCCESS(f"Eventos borrados: {deleted}."))
