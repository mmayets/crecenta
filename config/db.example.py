"""Conexión a PostgreSQL de este entorno.

Copie este archivo a `config/db.py` y ajuste los valores. `config/db.py` no se sube al
repositorio. El resto de la configuración vive en la tabla `parameters` de esta misma base
(ver `config/parameters.py`).
"""

DATABASE = {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": "crecenta",
    "USER": "crecenta",
    "PASSWORD": "crecenta",
    "HOST": "localhost",
    "PORT": "5432",
}

# Cuenta administradora de PostgreSQL (la que creó al instalarlo; suele ser "postgres").
# Solo la usa `python manage.py preparar_bd_local` para crear el usuario y la base.
POSTGRES_ADMIN_URL = "postgres://postgres:postgres@localhost:5432/postgres"
