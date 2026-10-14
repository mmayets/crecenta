# Crecenta

PWA de finanzas personales y para pequeños negocios (Django · PostgreSQL · HTMX · Alpine · Tailwind).

> **Persona:** organiza tu dinero, conoce cuánto puedes gastar y recibe orientación antes de que tu
> presupuesto se salga de control.
> **Negocio:** conoce tus costos, fija precios rentables y descubre cuánto ganas realmente.

Principio rector: **los números los calcula el código; la IA captura, explica y anticipa.** Las
cifras salen de servicios Python con `Decimal`; la IA recibe el resultado ya calculado, responde
JSON validado y nunca aplica nada sin que la persona lo acepte.

## Documentación

- [Arquitectura y plan](docs/arquitectura.md)
- [Decisiones tomadas](docs/decisiones.md)
- [Fase 1: criterios de aceptación y evidencia](docs/fase1.md)
- [Fase 2: pequeños negocios (diseño, reglas contables y evidencia)](docs/fase2.md)
- [Fase 3: inventario, compras, reportes e ITBIS (diseño y evidencia)](docs/fase3.md)
- [Fase 4: equipo, recetas, monedas, ventas sin conexión y 606/607 (diseño y evidencia)](docs/fase4.md)
- [Seguridad y privacidad](docs/seguridad.md)
- [Abrir en PyCharm con PostgreSQL local](docs/pycharm.md)

## PyCharm / desarrollo local con PostgreSQL instalado

Guía paso a paso: [docs/pycharm.md](docs/pycharm.md). En resumen:

```bash
uv sync
cp config/db.example.py config/db.py        # conexión; ajuste la clave de su usuario postgres
uv run python manage.py preparar_bd_local   # crea usuario y base, migra y carga la demo
uv run python manage.py importar_parametros .env.local.example   # resto → tabla parameters
uv run python manage.py runserver
# http://localhost:8000  ·  demo@crecenta.app / Demo-Crecenta-2026
# vendedora de Dulces Ariel: vendedor@crecenta.app (misma contraseña)
```

En PyCharm las configuraciones de ejecución ya vienen en `.run/` ("1 · Preparar base de datos
local" y "2 · Servidor Django"). Redis es opcional en local.

### Sin uv (pip)

`requirements.txt` trae las dependencias de producción y `requirements-dev.txt` también las de
pruebas y calidad (pytest, ruff, mypy), con las mismas versiones que `uv.lock`:

```bash
python -m venv .venv && .venv\Scripts\activate      # en Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt                  # o requirements.txt en un servidor
```

Si cambias dependencias en `pyproject.toml`, regenéralos:

```bash
uv export --format requirements-txt --no-hashes --no-dev --no-emit-project -o requirements.txt
uv export --format requirements-txt --no-hashes --no-emit-project -o requirements-dev.txt
```

## Desarrollo local (manual)

Requiere Python 3.12, PostgreSQL 16, Redis y [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp config/db.example.py config/db.py   # ponga su usuario, clave y base
uv run python manage.py migrate
uv run python manage.py seed_demo      # persona RD$50,000 + negocio Dulces Ariel con ventas
uv run python manage.py runserver
uv run celery -A config worker -l info # explicaciones con IA, lectura de comprobantes, alertas
uv run celery -A config beat -l info   # alertas diarias
```

### IA

`AI_PROVIDER=fake` (por defecto) funciona sin claves: explicaciones por reglas y sin lectura de
comprobantes/voz. Para usar un proveedor real:

```bash
AI_PROVIDER=gemini  GEMINI_API_KEY=…   # o
AI_PROVIDER=openai  OPENAI_API_KEY=…
```

Cada persona debe activar el uso de IA en *Configuración y privacidad*.

## Calidad

```bash
make lint          # ruff
make typecheck     # mypy sobre la capa de cálculo
make cov-services  # pytest + cobertura ≥ 90 % en services/
make check-deploy  # manage.py check --deploy con settings de producción
make check         # todo lo anterior
make css           # compila Tailwind (CLI standalone en bin/tailwindcss)
make e2e           # prueba E2E de la PWA sin conexión (Chromium + Playwright de Node)
```

Los tests usan PostgreSQL (`TEST_DATABASE_URL` o `DATABASE_URL`; por defecto
`postgres://postgres:postgres@localhost:5432/crecenta`).

## Estructura

```
apps/
  core/        dinero, fechas, períodos, límites de uso, íconos, seed_demo
  accounts/    usuario por correo, consentimiento de IA, exportar y eliminar
  workspaces/  espacios persona/negocio y aislamiento
  onboarding/  wizard por pasos y modo conversacional
  ledger/      cuentas, categorías, movimientos, sincronización offline
  personal/    motor del plan, línea de tiempo de caja, alternativas, disponible
  planning/    versiones del plan, explicación con IA, aceptar/editar/descartar
  alerts/      reglas, evaluación diaria y tras cada movimiento
  receipts/    comprobantes, lectura con IA, duplicados, revisión
  ai/          proveedores (Gemini, OpenAI, prueba), esquemas, prompts, verificación de cifras
  reports/     tablero de inicio
  pwa/         manifest, service worker, páginas sin conexión
  business/    perfil y productos (base de la Fase 2)
  pricing/     precio por margen y por recargo
```
