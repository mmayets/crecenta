import pytest
from django.core.cache import cache

from apps.accounts.tests.factories import UserFactory
from apps.ai.providers import FakeProvider
from apps.workspaces.services.workspaces import create_workspace


@pytest.fixture
def user(db):
    return UserFactory(email="ariel@example.com")


@pytest.fixture
def other_user(db):
    return UserFactory(email="beto@example.com")


@pytest.fixture
def personal_ws(user):
    return create_workspace(user, "personal")


@pytest.fixture
def business_ws(user):
    return create_workspace(user, "business", name="Dulces Ariel")


@pytest.fixture
def other_ws(other_user):
    return create_workspace(other_user, "personal")


@pytest.fixture(autouse=True)
def _clean_ai_state():
    """Cada test empieza sin respuestas programadas de IA ni contadores de límite."""
    FakeProvider.reset()
    cache.clear()
    yield
    FakeProvider.reset()
