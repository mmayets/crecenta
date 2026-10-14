from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.accounts.services.privacy import delete_account
from apps.accounts.tests.factories import UserFactory
from apps.backoffice.models import AuditEvent
from apps.backoffice.services import stats
from apps.core.models import Parameter
from apps.ledger.models import Account
from apps.ledger.services.recording import TxData, record_transaction

pytestmark = pytest.mark.django_db
Kind = AuditEvent.Kind


@pytest.fixture
def staff(db):
    return UserFactory(email="admin@example.com", is_staff=True)


@pytest.fixture
def admin_client(client, staff):
    client.force_login(staff)
    return client


PANEL_URLS = ["overview", "behavior", "finances", "users", "audit", "parameters", "parameter_new"]


# ---------------------------------------------------------------- acceso


@pytest.mark.parametrize("name", PANEL_URLS)
def test_solo_el_equipo_entra_al_panel(client, user, name):
    url = reverse(f"panel:{name}")
    assert reverse("account_login") in client.get(url)["Location"]
    client.force_login(user)
    assert client.get(url).status_code == 404


@pytest.mark.parametrize("name", PANEL_URLS)
def test_el_equipo_ve_cada_seccion(admin_client, name):
    assert admin_client.get(reverse(f"panel:{name}")).status_code == 200


def test_la_barra_lateral_muestra_administracion_solo_al_equipo(client, user, staff):
    client.force_login(user)
    assert (
        'data-testid="administracion"'
        not in client.get(reverse("workspaces:selector")).content.decode()
    )
    client.force_login(staff)
    assert (
        'data-testid="administracion"'
        in client.get(reverse("workspaces:selector")).content.decode()
    )


# ---------------------------------------------------------------- auditoría


def test_las_acciones_y_visitas_quedan_auditadas(client, user, personal_ws):
    client.force_login(user)
    client.get(reverse("espacio:dashboard", kwargs={"ws": personal_ws.pk}))
    account = Account.objects.for_workspace(personal_ws).first()
    client.post(
        reverse("ledger:new", kwargs={"ws": personal_ws.pk}),
        {"kind": "gasto", "amount": "350", "account": account.pk, "date": "2026-10-10",
         "client_uuid": "1b8a4f6e-3c2d-4e5f-8a9b-0c1d2e3f4a5b", "source": "manual"},
    )  # fmt: skip
    visit = AuditEvent.objects.get(kind=Kind.VISITA, action="espacio:dashboard")
    assert visit.user == user and visit.workspace_id == personal_ws.pk and visit.status == 200
    action = AuditEvent.objects.get(kind=Kind.ACCION, action="ledger:new")
    assert action.description == "Registró un movimiento"
    assert action.user_email == user.email and action.method == "POST"
    # Nunca se guarda el contenido del formulario.
    assert "350" not in str(action.data) and "350" not in action.path


def test_htmx_y_estaticos_no_cuentan_como_visita(client, user, personal_ws):
    client.force_login(user)
    client.get(
        reverse("onboarding:guide", kwargs={"ws": personal_ws.pk}), headers={"HX-Request": "true"}
    )
    client.get("/sw.js")
    assert not AuditEvent.objects.filter(kind=Kind.VISITA).exists()


def test_accesos_quedan_auditados(client, user):
    client.post(reverse("account_login"), {"login": user.email, "password": "mala"})
    failed = AuditEvent.objects.get(action="inicio_fallido")
    assert failed.user is None and failed.user_email == user.email and failed.status == 401
    client.post(reverse("account_login"), {"login": user.email, "password": "Clave-Segura-2026"})
    assert AuditEvent.objects.filter(action="inicio_sesion", user=user).exists()
    client.post(reverse("account_logout"))
    assert AuditEvent.objects.filter(action="cierre_sesion", user=user).exists()


def test_registro_queda_auditado(client):
    client.post(
        reverse("account_signup"),
        {"email": "nueva@example.com", "password1": "Clave-Segura-2026",
         "password2": "Clave-Segura-2026"},
    )  # fmt: skip
    assert AuditEvent.objects.filter(action="registro", user_email="nueva@example.com").exists()


def test_filtros_y_csv_de_auditoria(admin_client, user):
    AuditEvent.objects.create(
        user=user,
        user_email=user.email,
        kind=Kind.ACCION,
        action="ledger:new",
        description="Registró un movimiento",
        status=302,
    )
    AuditEvent.objects.create(user_email="otra@example.com", kind=Kind.ACCESO,
                              action="inicio_fallido", description="Fallido",
                              status=401)  # fmt: skip
    html = admin_client.get(reverse("panel:audit"), {"usuario": "ana@"}).content.decode()
    assert 'data-evento="ledger:new"' in html and 'data-evento="inicio_fallido"' not in html
    html = admin_client.get(reverse("panel:audit"), {"resultado": "errores"}).content.decode()
    assert 'data-evento="inicio_fallido"' in html and 'data-evento="ledger:new"' not in html
    response = admin_client.get(reverse("panel:audit"), {"tipo": "accion", "formato": "csv"})
    body = b"".join(response.streaming_content).decode()
    assert response["Content-Type"].startswith("text/csv")
    assert "ledger:new" in body and "inicio_fallido" not in body
    assert AuditEvent.objects.filter(action="panel:auditoria_csv").exists()


def test_al_eliminar_la_cuenta_la_auditoria_se_anonimiza(user):
    AuditEvent.objects.create(user=user, user_email=user.email, kind=Kind.ACCION,
                              action="ledger:new", description="x", ip="10.0.0.1")  # fmt: skip
    delete_account(user)
    event = AuditEvent.objects.get(action="ledger:new")
    assert (event.user, event.user_email, event.ip) == (None, "(cuenta eliminada)", None)


def test_ficha_de_usuario_muestra_su_actividad(admin_client, user):
    AuditEvent.objects.create(user=user, user_email=user.email, kind=Kind.ACCION,
                              action="planning:accept", description="Aceptó un plan")  # fmt: skip
    html = admin_client.get(reverse("panel:user_detail", args=[user.pk])).content.decode()
    assert user.email in html and "Aceptó un plan" in html


# ---------------------------------------------------------------- parámetros


def test_crear_editar_y_eliminar_parametros(admin_client):
    response = admin_client.post(
        reverse("panel:parameter_new"),
        {"key": "ai_provider", "value": "gemini", "description": "Proveedor de IA"},
    )
    assert response["Location"] == reverse("panel:parameters")
    parameter = Parameter.objects.get(key="AI_PROVIDER")
    assert parameter.value == "gemini"
    admin_client.post(
        reverse("panel:parameter_edit", args=[parameter.pk]),
        {"key": "OTRA", "value": "openai", "description": ""},
    )
    parameter.refresh_from_db()
    assert (parameter.key, parameter.value) == ("AI_PROVIDER", "openai")  # la clave no cambia
    event = AuditEvent.objects.get(action="panel:parametro_editado")
    assert event.data == {"clave": "AI_PROVIDER", "valor_cambiado": True}
    admin_client.post(reverse("panel:parameter_delete", args=[parameter.pk]))
    assert not Parameter.objects.filter(key="AI_PROVIDER").exists()


def test_los_secretos_no_se_muestran_ni_se_pierden(admin_client):
    secret = Parameter.objects.create(key="GOOGLE_CLIENT_SECRET", value="super-secreto")
    html = admin_client.get(reverse("panel:parameters")).content.decode()
    assert "super-secreto" not in html and "••••••" in html
    form = admin_client.get(reverse("panel:parameter_edit", args=[secret.pk])).content.decode()
    assert "super-secreto" not in form
    admin_client.post(
        reverse("panel:parameter_edit", args=[secret.pk]), {"value": "", "description": "x"}
    )
    secret.refresh_from_db()
    assert secret.value == "super-secreto"
    assert "super-secreto" not in str(AuditEvent.objects.get(action="panel:parametro_editado").data)


def test_claves_reservadas_o_invalidas(admin_client):
    for key in ("DATABASE_URL", "con espacios"):
        response = admin_client.post(reverse("panel:parameter_new"), {"key": key, "value": "x"})
        assert response.status_code == 400
    assert not Parameter.objects.exists()


# ---------------------------------------------------------------- estadísticas


def test_estadisticas_de_uso_y_comportamiento(user, personal_ws):
    AuditEvent.objects.create(
        user=user,
        user_email=user.email,
        kind=Kind.VISITA,
        action="ledger:movements",
        description="v",
    )
    AuditEvent.objects.create(user=user, user_email=user.email, kind=Kind.ACCION,
                              action="ledger:new", description="a")  # fmt: skip
    usage = stats.usage(7)
    assert usage["users_total"] == 1 and usage["active_7"] == 1
    assert usage["workspaces"] == {"personal": 1}
    assert sum(usage["series"]["activos"]) == 1 and len(usage["labels"]) == 7
    behavior = stats.behavior(7)
    assert behavior["sections"] == [("Movimientos", 1)]
    assert behavior["actions"][0]["label"] == "Registró un movimiento"
    assert behavior["funnel"][1] == ("Crearon un espacio", 1)


def test_finanzas_agregadas_por_moneda(user, personal_ws):
    account = Account.objects.for_workspace(personal_ws).first()
    from apps.ledger.choices import Direction, TxKind

    today = date.today()
    for amount, direction, kind in (
        ("50000", Direction.IN, TxKind.INGRESO),
        ("1200", Direction.OUT, TxKind.GASTO),
        ("3000", Direction.IN, TxKind.PRESTAMO),
    ):
        data = TxData(account=account, date=today, amount=Decimal(amount), direction=direction,
                      kind=kind)  # fmt: skip
        record_transaction(personal_ws, user, data)
    data = stats.finances()
    table = data["tables"][0]
    assert table["currency"] == "DOP"
    current = table["rows"][-1]
    # Un préstamo recibido mueve dinero, pero no es ingreso.
    assert (current["p_in"], current["p_out"], current["p_net"]) == (
        D := Decimal("50000"),
        Decimal("1200"),
        D - Decimal("1200"),
    )
