"""Carga en la tabla `parameters` los valores de un archivo con formato `.env`.

Uso:
    python manage.py importar_parametros .env.local.example
    python manage.py importar_parametros mi.env --no-sobrescribir

No importa la conexión a la base de datos (va en `config/db.py`) ni DJANGO_SETTINGS_MODULE, que
decide qué ajustes se cargan antes de poder leer la tabla.
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core.models import Parameter

EXCLUDED = {"DATABASE_URL", "TEST_DATABASE_URL", "POSTGRES_ADMIN_URL", "DJANGO_SETTINGS_MODULE"}


def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip().removeprefix("export ").strip()] = value
    return values


class Command(BaseCommand):
    help = "Carga en la tabla parameters los valores de un archivo .env."

    def add_arguments(self, parser) -> None:
        parser.add_argument("archivo", help="Archivo con líneas CLAVE=valor")
        parser.add_argument(
            "--no-sobrescribir", action="store_true", help="Deja como están las claves existentes"
        )

    def handle(self, *args, archivo: str, no_sobrescribir: bool, **options):
        path = Path(archivo)
        if not path.is_file():
            raise CommandError(f"No encuentro el archivo «{archivo}».")
        created = updated = 0
        for key, value in parse_env(path.read_text(encoding="utf-8-sig")).items():
            if key in EXCLUDED:
                continue
            if no_sobrescribir:
                _, was_created = Parameter.objects.get_or_create(key=key, defaults={"value": value})
            else:
                _, was_created = Parameter.objects.update_or_create(
                    key=key, defaults={"value": value}
                )
            created += was_created
            updated += not was_created and not no_sobrescribir
        self.stdout.write(
            self.style.SUCCESS(f"Parámetros: {created} creados, {updated} actualizados.")
        )
        self.stdout.write("Reinicie el servidor para que tomen efecto.")
