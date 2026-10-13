"""Crea en el PostgreSQL local el usuario y la base de datos de la app, aplica las migraciones y
(opcionalmente) carga la demo. Pensado para el primer arranque en PyCharm o desde la terminal.

Uso:
    python manage.py preparar_bd_local                 # crea, migra y carga la demo
    python manage.py preparar_bd_local --sin-demo
    python manage.py preparar_bd_local --admin-url postgres://postgres:CLAVE@localhost:5432/postgres

Lee la base de destino y la cuenta administradora (POSTGRES_ADMIN_URL) de config/db.py o, si
existen, de las variables de entorno (por defecto la cuenta postgres:postgres en localhost).
Es idempotente: si el usuario o la base ya existen, no los toca.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import psycopg
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from psycopg import sql

DEFAULT_ADMIN_URL = "postgres://postgres:postgres@localhost:5432/postgres"


def _target() -> dict[str, Any]:
    db = settings.DATABASES["default"]
    if "postgresql" not in db["ENGINE"]:
        raise CommandError("La base de datos configurada debe ser PostgreSQL.")
    return {
        "name": db["NAME"],
        "user": db["USER"],
        "password": db.get("PASSWORD") or "",
        "host": db.get("HOST") or "localhost",
        "port": str(db.get("PORT") or 5432),
    }


def ensure_database(admin_url: str, target: dict[str, Any]) -> list[str]:
    """Crea el rol (con permiso para crear la base de los tests) y la base si faltan.
    Devuelve lo que hizo, en texto."""
    done: list[str] = []
    with psycopg.connect(admin_url, autocommit=True, connect_timeout=5) as conn:
        role_exists = conn.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s", [target["user"]]
        ).fetchone()
        if not role_exists:
            conn.execute(
                sql.SQL("CREATE ROLE {} LOGIN CREATEDB PASSWORD {}").format(
                    sql.Identifier(target["user"]), sql.Literal(target["password"])
                )
            )
            done.append(f"Usuario «{target['user']}» creado.")
        else:
            done.append(f"El usuario «{target['user']}» ya existía.")
        db_exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", [target["name"]]
        ).fetchone()
        if not db_exists:
            conn.execute(
                sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8' TEMPLATE template0").format(
                    sql.Identifier(target["name"]), sql.Identifier(target["user"])
                )
            )
            done.append(f"Base de datos «{target['name']}» creada.")
        else:
            done.append(f"La base de datos «{target['name']}» ya existía.")
    return done


class Command(BaseCommand):
    help = "Crea el usuario y la base de datos en el PostgreSQL local, migra y carga la demo."
    requires_system_checks: list[str] = []  # la base todavía puede no existir

    def add_arguments(self, parser) -> None:
        parser.add_argument("--admin-url", default=None, help="Cuenta administradora de PostgreSQL")
        parser.add_argument("--sin-demo", action="store_true", help="No cargar la demo")
        parser.add_argument("--solo-crear", action="store_true", help="No migrar ni cargar demo")

    def handle(self, *args, admin_url: str | None, sin_demo: bool, solo_crear: bool, **options):
        admin_url = admin_url or settings.POSTGRES_ADMIN_URL or DEFAULT_ADMIN_URL
        target = _target()
        admin = urlsplit(admin_url)  # se muestra sin la clave
        self.stdout.write(
            f"PostgreSQL: {target['host']}:{target['port']} · base «{target['name']}» · "
            f"administrador «{admin.username}» en {admin.hostname}:{admin.port or 5432}"
        )
        try:
            for line in ensure_database(admin_url, target):
                self.stdout.write(f"  {line}")
        except psycopg.OperationalError as exc:
            raise CommandError(
                "No pude conectarme con la cuenta administradora de PostgreSQL. Revise que el "
                "servicio esté encendido y que POSTGRES_ADMIN_URL (o --admin-url) tenga el usuario "
                f"y la clave correctos.\nDetalle: {exc}"
            ) from exc
        if solo_crear:
            return
        call_command("migrate", interactive=False, verbosity=1, stdout=self.stdout)
        if not sin_demo:
            call_command("seed_demo", stdout=self.stdout)
        self.stdout.write(self.style.SUCCESS("Base de datos lista. Arranque el servidor."))
