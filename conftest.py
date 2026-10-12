import pytest

from apps.accounts.tests.factories import UserFactory
from apps.workspaces.services.workspaces import create_workspace


@pytest.fixture
def user(db):
    return UserFactory(email="ana@example.com")


@pytest.fixture
def other_user(db):
    return UserFactory(email="beto@example.com")


@pytest.fixture
def personal_ws(user):
    return create_workspace(user, "personal")


@pytest.fixture
def business_ws(user):
    return create_workspace(user, "business", name="Dulces Ana")


@pytest.fixture
def other_ws(other_user):
    return create_workspace(other_user, "personal")
