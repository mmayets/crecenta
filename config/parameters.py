"""Parámetros de configuración guardados en la tabla `parameters` de la base de datos.

Se leen una vez, al cargar los ajustes, y se exponen como variables de entorno para que
`config/settings` los consuma igual que antes. Una variable de entorno real siempre gana sobre
la tabla (p. ej. en CI). Como se leen al arrancar, un cambio en la tabla requiere reiniciar el
servidor.
"""

from __future__ import annotations

import os
from typing import Any

import psycopg

TABLE = "parameters"


def load_parameters(db: dict[str, Any]) -> None:
    """Copia cada fila de la tabla a `os.environ` si la clave no está definida ya.

    Si la base no responde o la tabla todavía no existe (antes del primer `migrate`), no hace
    nada y los ajustes usan sus valores por defecto.
    """
    conninfo = {
        "dbname": db.get("NAME"),
        "user": db.get("USER"),
        "password": db.get("PASSWORD"),
        "host": db.get("HOST"),
        "port": db.get("PORT"),
    }
    try:
        with psycopg.connect(connect_timeout=3, **{k: v for k, v in conninfo.items() if v}) as conn:
            rows = conn.execute(f"SELECT key, value FROM {TABLE}").fetchall()  # noqa: S608
    except psycopg.Error:
        return
    for key, value in rows:
        os.environ.setdefault(key, value)
