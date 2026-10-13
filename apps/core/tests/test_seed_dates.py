import datetime
from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command

from apps.planning.models import PlanVersion

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "today", [datetime.date(2026, 3, 1), datetime.date(2026, 2, 28), datetime.date(2026, 1, 31)]
)
def test_demo_funciona_cualquier_dia_del_mes(today):
    with mock.patch("django.utils.timezone.localdate", return_value=today):
        call_command("seed_demo", stdout=StringIO())
    plan = PlanVersion.objects.get(kind="business")
    assert plan.plan_status in {"viable", "ajustado"} and plan.period_start == today.replace(day=1)
