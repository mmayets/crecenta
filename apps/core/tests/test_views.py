import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_salud(client):
    response = client.get(reverse("core:health"))
    assert response.status_code == 200
    assert response.json() == {"estado": "ok"}


def test_cabeceras_de_seguridad(client):
    response = client.get(reverse("core:health"))
    assert "frame-ancestors 'none'" in response["Content-Security-Policy"]
    assert "microphone=(self)" in response["Permissions-Policy"]
    assert response["X-Frame-Options"] == "DENY"
    assert response["X-Content-Type-Options"] == "nosniff"


def test_campo_monetario_estandar():
    from apps.core.models import money_field

    field = money_field("monto")
    assert (field.max_digits, field.decimal_places) == (14, 2)
