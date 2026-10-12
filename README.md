# Crecenta

PWA de finanzas personales y para pequeños negocios (Django · PostgreSQL · HTMX).

- Arquitectura y plan: [`docs/arquitectura.md`](docs/arquitectura.md)
- Decisiones: [`docs/decisiones.md`](docs/decisiones.md)

## Desarrollo con Docker

```bash
cp .env.example .env
docker compose up --build
# http://localhost:8000
```

## Desarrollo local (sin Docker)

Requiere Python 3.12, PostgreSQL 16, Redis y [uv](https://docs.astral.sh/uv/).

```bash
uv sync
export DATABASE_URL=postgres://usuario:clave@localhost:5432/crecenta
uv run python manage.py migrate
uv run python manage.py runserver
```

## Calidad

```bash
make lint          # ruff
make typecheck     # mypy sobre la capa de cálculo
make cov-services  # pytest + cobertura ≥ 90 % en services/
make check-deploy  # manage.py check --deploy con settings de producción
make check         # todo lo anterior
make css           # compila Tailwind (bin/tailwindcss)
make e2e           # prueba E2E de la PWA sin conexión (Chromium + Playwright de Node)
```

Los tests usan PostgreSQL (`TEST_DATABASE_URL` o `DATABASE_URL`; por defecto
`postgres://postgres:postgres@localhost:5432/crecenta`).
