# Abrir Crecenta en PyCharm (con PostgreSQL local)

Funciona en Windows, macOS y Linux, con PyCharm Community o Professional (2024.3 o superior).

## 1. Lo que necesita instalado

| Programa | Para qué | Nota |
|---|---|---|
| **Python 3.12** | la app | En Windows, marque "Add python.exe to PATH". |
| **PostgreSQL 16** | la base de datos | Anote la clave que le pide para el usuario `postgres` al instalar. |
| **uv** | instala las dependencias | `pip install uv` (o ver https://docs.astral.sh/uv/). |
| Redis | *opcional* | No hace falta: sin Redis la app usa caché en memoria y hace las tareas en el mismo proceso. |
| Node.js | *opcional* | Solo para la prueba E2E. El CSS ya viene compilado. |

## 2. Abrir el proyecto

1. PyCharm → **Open** → elija la carpeta `crecenta` (la que tiene `manage.py`).
2. Abra la **Terminal** de PyCharm (abajo) y ejecute:
   ```bash
   uv sync
   ```
   Crea el entorno virtual `.venv` con todas las dependencias.
3. Intérprete: si PyCharm no lo detecta solo, vaya a **Settings → Project → Python Interpreter →
   Add Interpreter → Add Local Interpreter → Existing** (o **uv**) y elija
   `.venv/Scripts/python.exe` (Windows) o `.venv/bin/python` (macOS/Linux).

## 3. Configurar la conexión (`config/db.py`)

Copie el archivo de ejemplo:

```bash
# Windows (PowerShell)
Copy-Item config/db.example.py config/db.py
# macOS / Linux
cp config/db.example.py config/db.py
```

Abra `config/db.py` (no se sube al repositorio) y revise dos cosas:

- `DATABASE`: la base de la app (el comando del paso 4 la crea con este usuario y clave).
- `POSTGRES_ADMIN_URL`: la cuenta administradora de su PostgreSQL; cambie "postgres" (la
  segunda) por SU clave. Si la clave tiene símbolos como `@`, `:` o `/`, escríbalos codificados
  (`@` → `%40`, `:` → `%3A`, `/` → `%2F`).

El resto de la configuración (clave secreta, modo depuración, Redis, IA, correo…) vive en la
tabla `parameters` de la base de datos. Después del paso 4, cárguela con los valores de ejemplo:

```bash
uv run python manage.py importar_parametros .env.local.example
```

Se editan desde el panel de administración (**Parámetros**) o con SQL; se leen al arrancar, así
que un cambio requiere reiniciar el servidor. Una variable de entorno con el mismo nombre gana
sobre la tabla.

## 4. Crear la base de datos

En la barra superior de PyCharm, en el selector de configuraciones, elija
**1 · Preparar base de datos local** y presione ▶ (Run).

Esto, usando la cuenta administradora:
1. crea el usuario `crecenta` (con permiso para crear la base de los tests) si no existe;
2. crea la base `crecenta` (UTF-8) si no existe;
3. aplica las migraciones;
4. carga la demo (persona RD$50,000 y el negocio "Dulces Ariel").

Puede repetirse sin problema: lo que ya existe no se toca. Desde la terminal es lo mismo:

```bash
uv run python manage.py preparar_bd_local            # o --sin-demo
```

## 5. Arrancar

Elija **2 · Servidor Django** → ▶ y abra http://127.0.0.1:8000

- Usuario de la demo: `demo@crecenta.app` · clave `Demo-Crecenta-2026`
- Para depurar con puntos de parada use 🐞 (Debug) en la misma configuración.

## Configuraciones incluidas (carpeta `.run/`)

| Configuración | Qué hace |
|---|---|
| 1 · Preparar base de datos local | `manage.py preparar_bd_local` |
| 2 · Servidor Django | `manage.py runserver 127.0.0.1:8000` |
| Demo · recrear datos | `manage.py seed_demo --reset` (borra solo la cuenta de demostración) |
| Migraciones · aplicar | `manage.py migrate` |
| Tests (pytest) | toda la suite (crea y borra su propia base `test_crecenta`) |
| Celery worker (opcional, con Redis) | solo si puso `REDIS_URL` en la tabla `parameters`; usa `--pool=solo` para Windows |

## PyCharm Professional: soporte de Django (opcional)

**Settings → Languages & Frameworks → Django**: active *Enable Django Support*, *Django project
root* = la carpeta del proyecto, *Settings* = `config/settings/dev.py`, *Manage script* =
`manage.py`. Así funcionan el autocompletado en plantillas y la ventana *manage.py tasks*.

**Ver la base de datos** (pestaña *Database*): **+ → Data Source → PostgreSQL**, host `localhost`,
puerto `5432`, usuario `crecenta`, clave `crecenta`, base `crecenta`.

## Problemas frecuentes

| Mensaje | Qué hacer |
|---|---|
| `No pude conectarme con la cuenta administradora` | PostgreSQL apagado (Windows: *Servicios* → `postgresql-x64-16` → Iniciar) o clave equivocada en `POSTGRES_ADMIN_URL`. |
| `password authentication failed for user "crecenta"` | El usuario ya existía con otra clave: cámbiela en pgAdmin o ponga esa clave en `config/db.py`. |
| `could not connect to server … port 5432` | PostgreSQL usa otro puerto (p. ej. 5433): cámbielo en `config/db.py` (en `DATABASE` y en la URL). |
| `ModuleNotFoundError: django` | PyCharm no está usando `.venv`: revise el intérprete (paso 2). |
| Los tests fallan con `permission denied to create database` | El usuario de `config/db.py` no tiene `CREATEDB`: `ALTER ROLE crecenta CREATEDB;` |
| Quiero crear la base a mano (pgAdmin / psql) | `CREATE ROLE crecenta LOGIN CREATEDB PASSWORD 'crecenta';` y `CREATE DATABASE crecenta OWNER crecenta ENCODING 'UTF8' TEMPLATE template0;`, luego **Migraciones · aplicar**. |

En Windows no hay `make`: los comandos de calidad equivalentes son
`uv run ruff check .`, `uv run mypy …` (ver `Makefile`) y `uv run pytest`.
