"""Genera las claves VAPID de las notificaciones push y las guarda en la tabla `parameters`.

Uso: python manage.py generar_vapid [--correo soporte@midominio.com] [--reemplazar]

Si ya existen, no se tocan (cambiarlas invalida las suscripciones actuales) salvo con
--reemplazar. Después hay que reiniciar el servidor.
"""

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.core.management.base import BaseCommand

from apps.core.models import Parameter


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class Command(BaseCommand):
    help = "Genera las claves VAPID para las notificaciones push."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--correo", default="soporte@crecenta.app")
        parser.add_argument("--reemplazar", action="store_true")

    def handle(self, *args, correo: str, reemplazar: bool, **options) -> None:
        if Parameter.objects.filter(key="VAPID_PRIVATE_KEY").exists() and not reemplazar:
            self.stdout.write("Las claves VAPID ya existen. Usa --reemplazar para cambiarlas.")
            return
        key = ec.generate_private_key(ec.SECP256R1())
        private = _b64url(key.private_numbers().private_value.to_bytes(32, "big"))
        public = _b64url(
            key.public_key().public_bytes(
                serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
            )
        )
        values = {
            "VAPID_PUBLIC_KEY": (public, "Notificaciones push: clave pública"),
            "VAPID_PRIVATE_KEY": (private, "Notificaciones push: clave privada"),
            "VAPID_SUBJECT": (f"mailto:{correo}", "Notificaciones push: contacto del remitente"),
        }
        for name, (value, description) in values.items():
            Parameter.objects.update_or_create(
                key=name, defaults={"value": value, "description": description}
            )
        self.stdout.write(self.style.SUCCESS("Claves VAPID guardadas. Reinicia el servidor."))
