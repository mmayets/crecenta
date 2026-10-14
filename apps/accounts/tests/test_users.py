import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

pytestmark = pytest.mark.django_db
User = get_user_model()


def test_crear_usuario_normaliza_correo():
    user = User.objects.create_user("Ariel@Example.COM", "clave-segura-123")
    assert user.email == "ariel@example.com"
    assert user.check_password("clave-segura-123")
    assert not user.is_staff
    assert str(user) == "ariel@example.com"
    assert user.get_short_name() == "ariel"
    assert user.get_full_name() == "ariel@example.com"


def test_correo_obligatorio():
    with pytest.raises(ValueError):
        User.objects.create_user("", "x")


def test_superusuario():
    admin = User.objects.create_superuser("admin@example.com", "clave-segura-123")
    assert admin.is_staff and admin.is_superuser
    with pytest.raises(ValueError):
        User.objects.create_superuser("otro@example.com", "x", is_staff=False)


def test_consentimiento_ia():
    user = User.objects.create_user("ariel@example.com", "clave-segura-123", first_name="Ariel")
    assert user.get_short_name() == "Ariel"
    assert not user.ai_consent
    user.set_ai_consent(True)
    user.refresh_from_db()
    assert user.ai_consent and user.ai_consent_at is not None
    user.set_ai_consent(False)
    user.refresh_from_db()
    assert not user.ai_consent and user.ai_consent_at is None


def test_registro_con_correo(client):
    response = client.post(
        reverse("account_signup"),
        {
            "email": "nuevo@example.com",
            "password1": "Clave-Segura-2026",
            "password2": "Clave-Segura-2026",
        },
    )
    assert response.status_code == 302
    assert User.objects.filter(email="nuevo@example.com").exists()


def test_inicio_de_sesion_con_correo(client):
    User.objects.create_user("ariel@example.com", "Clave-Segura-2026")
    response = client.post(
        reverse("account_login"), {"login": "ariel@example.com", "password": "Clave-Segura-2026"}
    )
    assert response.status_code == 302
    assert response["Location"] == reverse("home")
