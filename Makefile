.PHONY: lint fmt test cov-services typecheck check-deploy check

lint:
	uv run ruff check .
	uv run ruff format --check .

fmt:
	uv run ruff check --fix .
	uv run ruff format .

test:
	uv run pytest

# Cobertura exigida (≥ 90 %) sobre la capa de cálculo.
cov-services: test
	uv run coverage report --include='apps/*/services/*,apps/core/money.py,apps/core/dates.py,apps/core/periods.py' --fail-under=90

TYPED := apps/core/money.py apps/core/dates.py apps/core/periods.py $(wildcard apps/*/services)

typecheck:
	uv run mypy $(TYPED)

check-deploy:
	DJANGO_SETTINGS_MODULE=config.settings.prod \
	DJANGO_SECRET_KEY=$$(python3 -c 'import secrets;print(secrets.token_urlsafe(50))') \
	DJANGO_ALLOWED_HOSTS=crecenta.example \
	uv run python manage.py check --deploy --fail-level WARNING

check: lint typecheck cov-services check-deploy
