# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencias primero para aprovechar la caché de capas.
COPY pyproject.toml uv.lock ./
ARG UV_GROUPS="--no-dev"
RUN uv sync --frozen $UV_GROUPS

COPY . .

RUN useradd --create-home --uid 1000 app && mkdir -p /app/media /app/staticfiles \
    && chown -R app:app /app/media /app/staticfiles
USER app

# ---------------------------------------------------------------- producción
FROM base AS prod
ENV DJANGO_SETTINGS_MODULE=config.settings.prod
RUN DJANGO_SECRET_KEY=build-only DJANGO_ALLOWED_HOSTS=localhost \
    python manage.py collectstatic --noinput
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
