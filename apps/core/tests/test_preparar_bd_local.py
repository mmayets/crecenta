import os
import uuid
from io import StringIO
from unittest import mock

import psycopg
import pytest
from django.core.management import CommandError, call_command
from psycopg import sql

from apps.core.management.commands import preparar_bd_local as cmd

ADMIN_URL = os.environ.get("POSTGRES_ADMIN_URL", cmd.DEFAULT_ADMIN_URL)


def _admin_available() -> bool:
    try:
        psycopg.connect(ADMIN_URL, connect_timeout=2).close()
    except psycopg.OperationalError:
        return False
    return True


needs_admin = pytest.mark.skipif(not _admin_available(), reason="sin acceso de administrador")


@needs_admin
def test_crea_usuario_y_base_una_sola_vez():
    suffix = uuid.uuid4().hex[:8]
    target = {"name": f"crecenta_tmp_{suffix}", "user": f"crecenta_tmp_{suffix}",
              "password": "clave'con\"comillas", "host": "localhost", "port": "5432"}  # fmt: skip
    try:
        first = cmd.ensure_database(ADMIN_URL, target)
        assert first == [f"Usuario «{target['user']}» creado.",
                         f"Base de datos «{target['name']}» creada."]  # fmt: skip
        second = cmd.ensure_database(ADMIN_URL, target)
        assert all("ya existía" in line for line in second)
        url = f"postgres://{target['user']}@localhost:5432/{target['name']}"
        with psycopg.connect(url, password=target["password"]) as conn:
            owner = conn.execute(
                "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database()"
            ).fetchone()
            assert owner == (target["user"],)
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(target["name"]))
            )
            conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(target["user"])))


def test_comando_con_clave_incorrecta_explica_que_revisar():
    with pytest.raises(CommandError, match="cuenta administradora"):
        call_command(
            "preparar_bd_local",
            "--solo-crear",
            "--admin-url",
            "postgres://postgres:clave-equivocada@localhost:1/postgres",
            stdout=StringIO(),
        )


def test_comando_completo_llama_a_migrate_y_a_la_demo():
    out = StringIO()
    with (
        mock.patch.object(cmd, "ensure_database", return_value=["Usuario «x» creado."]),
        mock.patch.object(cmd, "call_command") as called,
    ):
        call_command("preparar_bd_local", "--admin-url", "postgres://a:b@h:5/p", stdout=out)
        assert [c.args[0] for c in called.call_args_list] == ["migrate", "seed_demo"]
        called.reset_mock()
        call_command("preparar_bd_local", "--sin-demo", stdout=out)
        assert [c.args[0] for c in called.call_args_list] == ["migrate"]
    text = out.getvalue()
    assert "administrador «a» en h:5" in text and ":b@" not in text  # no muestra la clave
    assert "Base de datos lista" in text


def test_exige_postgresql():
    sqlite = {"default": {"ENGINE": "django.db.backends.sqlite3"}}
    with (
        mock.patch.object(cmd.settings, "DATABASES", sqlite),
        pytest.raises(CommandError, match="PostgreSQL"),
    ):
        cmd._target()
