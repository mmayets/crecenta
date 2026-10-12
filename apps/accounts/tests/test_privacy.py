import io
import json
import zipfile
from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.accounts.models import User
from apps.ledger.models import Account, Transaction
from apps.ledger.services.recording import TxData, record_transaction
from apps.receipts.services.ingest import ingest_receipt
from apps.workspaces.models import Workspace

pytestmark = pytest.mark.django_db
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


@pytest.fixture
def datos(user, personal_ws, other_ws, other_user, django_capture_on_commit_callbacks):
    efectivo = Account.objects.for_workspace(personal_ws).get(name="Efectivo")
    record_transaction(
        personal_ws,
        user,
        TxData(
            account=efectivo,
            date=date(2026, 10, 5),
            amount="350",
            direction="out",
            kind="gasto",
            description="Colmado Juan",
        ),
    )
    with django_capture_on_commit_callbacks(execute=True):
        receipt = ingest_receipt(personal_ws, user, SimpleUploadedFile("f.png", PNG, "image/png"))
    otra = Account.objects.for_workspace(other_ws).get(name="Efectivo")
    record_transaction(
        other_ws,
        other_user,
        TxData(
            account=otra,
            date=date(2026, 10, 5),
            amount="999",
            direction="out",
            kind="gasto",
            description="Secreto de Beto",
        ),
    )
    return receipt


def test_configuracion_y_consentimiento(client, user):
    client.force_login(user)
    html = client.get(reverse("accounts:settings")).content.decode()
    assert "Qué compartimos con la IA" in html and "Nunca números de cuenta" in html
    client.post(reverse("accounts:settings"), {"first_name": "Ana", "ai_consent": "on"})
    user.refresh_from_db()
    assert user.first_name == "Ana" and user.ai_consent and user.ai_consent_at
    client.post(reverse("accounts:settings"), {"first_name": "Ana"})
    user.refresh_from_db()
    assert not user.ai_consent


def test_exportar_todo(client, user, datos):
    client.force_login(user)
    response = client.get(reverse("accounts:export"))
    assert response["Content-Type"] == "application/zip"
    assert "attachment" in response["Content-Disposition"]
    archive = zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content)))
    names = archive.namelist()
    assert "datos.json" in names
    assert any(n.startswith("comprobantes/") for n in names)
    data = json.loads(archive.read("datos.json"))
    assert data["usuario"]["correo"] == "ana@example.com"
    (espacio,) = data["espacios"]
    assert espacio["movimientos"][0]["description"] == "Colmado Juan"
    assert len(espacio["categorias"]) == 20 and espacio["comprobantes"]
    csv_name = next(n for n in names if n.endswith(".csv"))
    assert "Colmado Juan" in archive.read(csv_name).decode("utf-8-sig")
    assert b"Secreto de Beto" not in b"".join(archive.read(n) for n in names)


def test_eliminar_cuenta(
    client, user, other_user, datos, media, django_capture_on_commit_callbacks
):
    client.force_login(user)
    assert "no se puede deshacer" in client.get(reverse("accounts:delete")).content.decode()
    response = client.post(
        reverse("accounts:delete"),
        {"confirm_email": "otro@example.com", "password": "Clave-Segura-2026"},
    )
    assert response.status_code == 200 and User.objects.filter(pk=user.pk).exists()
    response = client.post(
        reverse("accounts:delete"), {"confirm_email": "ana@example.com", "password": "incorrecta"}
    )
    assert "La contraseña no es correcta" in response.content.decode()
    assert User.objects.filter(pk=user.pk).exists()
    file_path = media / datos.file.name
    assert file_path.exists()
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            reverse("accounts:delete"),
            {"confirm_email": "ANA@example.com", "password": "Clave-Segura-2026"},
        )
    assert response["Location"] == reverse("account_login")
    assert not User.objects.filter(pk=user.pk).exists()
    assert not Workspace.objects.filter(owner_id=user.pk).exists()
    assert not file_path.exists()
    # Los datos de otras personas no se tocan.
    assert Transaction.objects.filter(description="Secreto de Beto").exists()
    assert User.objects.filter(pk=other_user.pk).exists()
    assert client.get(reverse("accounts:settings")).status_code == 302  # sesión cerrada


def test_cuenta_sin_contrasena_solo_confirma_correo(client, user):
    user.set_unusable_password()
    user.save()
    client.force_login(user)
    assert "Tu contraseña" not in client.get(reverse("accounts:delete")).content.decode()
    client.post(reverse("accounts:delete"), {"confirm_email": "ana@example.com"})
    assert not User.objects.filter(pk=user.pk).exists()
