"""Equipo de un negocio: invitaciones por enlace, roles y lo que ve cada uno (docs/fase4.md §2)."""

import datetime
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory
from apps.business.models import Product, Receivable, Sale
from apps.business.services.sales import SaleData, SaleLineData, register_sale
from apps.ledger.models import Account
from apps.workspaces.models import Invitation, Membership, WorkspaceTransfer
from apps.workspaces.services import team
from apps.workspaces.services.transfers import transfer_between

pytestmark = pytest.mark.django_db
D = Decimal
VENDEDOR, ADMIN = Membership.Role.VENDEDOR, Membership.Role.ADMIN


@pytest.fixture
def carla(db):
    return UserFactory(email="carla@example.com")


def invitar(ws, by, email="carla@example.com", role=VENDEDOR):
    return team.create_invitation(ws, by, email, role)


def test_invitar_y_aceptar(user, business_ws, carla):
    inv, token = invitar(business_ws, user, " Carla@Example.com ", VENDEDOR)
    assert inv.email == "carla@example.com" and inv.token_hash != token
    assert len(token) >= 40 and team.find_invitation(token) == inv
    member = team.accept_invitation(carla, token)
    assert member.role == VENDEDOR and member.workspace == business_ws
    inv.refresh_from_db()
    assert inv.accepted_by == carla and inv.accepted_at
    with pytest.raises(ValidationError, match="ya se usó"):
        team.accept_invitation(carla, token)


def test_reglas_de_invitacion(user, other_user, personal_ws, business_ws, carla):
    with pytest.raises(ValidationError, match="personales no se comparten"):
        invitar(personal_ws, user)
    with pytest.raises(ValidationError, match="Solo el propietario"):
        invitar(business_ws, other_user)
    with pytest.raises(ValidationError):
        invitar(business_ws, user, role="owner")
    with pytest.raises(ValidationError):
        invitar(business_ws, user, email="ana@example.com")  # ya es miembro
    primera, _ = invitar(business_ws, user)
    segunda, token = invitar(business_ws, user, role=ADMIN)
    primera.refresh_from_db()
    assert primera.revoked_at and not segunda.revoked_at  # una vigente por correo
    assert team.invitation_problem(None) == "Este enlace no es válido."
    assert "es para carla@example.com" in team.invitation_problem(segunda, other_user)
    segunda.expires_at = timezone.now() - datetime.timedelta(minutes=1)
    segunda.save()
    with pytest.raises(ValidationError, match="venció"):
        team.accept_invitation(carla, token)
    with pytest.raises(ValidationError, match="no es válido"):
        team.accept_invitation(carla, "inventado")


def test_anular_cambiar_rol_y_quitar(user, business_ws, carla):
    inv, token = invitar(business_ws, user)
    team.revoke_invitation(business_ws, user, inv)
    assert "anulada" in team.invitation_problem(team.find_invitation(token))
    _, token = invitar(business_ws, user)
    member = team.accept_invitation(carla, token)
    assert team.change_role(business_ws, user, member, ADMIN).role == ADMIN
    with pytest.raises(ValidationError):
        team.change_role(business_ws, user, member, "owner")
    duena = Membership.objects.get(workspace=business_ws, user=user)
    with pytest.raises(ValidationError, match="propietario no se cambia"):
        team.change_role(business_ws, user, duena, ADMIN)
    with pytest.raises(ValidationError, match="Solo el propietario"):
        team.remove_member(business_ws, carla, duena)  # un admin no quita al dueño
    team.remove_member(business_ws, user, member)
    assert not Membership.objects.filter(user=carla).exists()


def test_no_mezcla_espacios(user, business_ws, carla):
    from apps.workspaces.services.workspaces import create_workspace

    otro = create_workspace(user, "business", name="Otro")
    inv, _ = invitar(otro, user)
    with pytest.raises(ValidationError):
        team.revoke_invitation(business_ws, user, inv)
    _, token = invitar(otro, user)
    member = team.accept_invitation(carla, token)
    with pytest.raises(ValidationError):
        team.change_role(business_ws, user, member, ADMIN)


def test_pantalla_de_equipo(client, user, business_ws, carla):
    client.force_login(user)
    url = reverse("espacio:team", kwargs={"ws": business_ws.pk})
    assert "personales nunca se comparten" in client.get(url).content.decode()
    html = client.post(url, {"email": "carla@example.com", "role": VENDEDOR}).content.decode()
    inv = Invitation.objects.get()
    assert "/invitacion/" in html and "solo se muestra ahora" in html
    assert inv.token_hash not in html  # se muestra el código, no su hash
    response = client.post(url, {"email": "ana@example.com", "role": VENDEDOR})
    assert response.status_code == 400 and "ya es parte" in response.content.decode()
    token = html.split("/invitacion/")[1].split("/")[0]

    # Carla acepta desde su sesión.
    client.force_login(carla)
    accept = reverse("workspaces:accept_invitation", kwargs={"token": token})
    assert "como <strong>vendedor</strong>" in client.get(accept).content.decode()
    response = client.post(accept)
    assert response["Location"] == reverse("espacio:dashboard", kwargs={"ws": business_ws.pk})
    member = Membership.objects.get(user=carla)
    assert client.post(accept).status_code == 400  # un solo uso

    client.force_login(user)
    kw = {"ws": business_ws.pk, "member_id": member.pk}
    client.post(reverse("espacio:member_role", kwargs=kw), {"role": ADMIN})
    member.refresh_from_db()
    assert member.role == ADMIN
    duena = Membership.objects.get(user=user)
    client.post(reverse("espacio:member_role", kwargs={**kw, "member_id": duena.pk}),
                {"role": ADMIN})  # fmt: skip
    assert Membership.objects.get(user=user).role == "owner"
    client.post(reverse("espacio:member_remove", kwargs={**kw, "member_id": duena.pk}))
    assert Membership.objects.filter(user=user).exists()
    client.post(reverse("espacio:member_remove", kwargs=kw))
    assert not Membership.objects.filter(user=carla).exists()
    assert client.post(reverse("espacio:member_remove", kwargs=kw)).status_code == 404

    client.post(url, {"email": "dani@example.com", "role": ADMIN})
    pendiente = Invitation.objects.get(email="dani@example.com")
    revoke = {"ws": business_ws.pk, "invitation_id": pendiente.pk}
    client.post(reverse("espacio:invitation_revoke", kwargs=revoke))
    pendiente.refresh_from_db()
    assert pendiente.revoked_at


def test_aceptar_con_otro_correo(client, user, business_ws, other_user):
    _, token = invitar(business_ws, user)
    client.force_login(other_user)
    response = client.get(reverse("workspaces:accept_invitation", kwargs={"token": token}))
    assert (
        response.status_code == 400 and "Inicia sesión con ese correo" in response.content.decode()
    )
    assert (
        client.post(reverse("workspaces:accept_invitation", kwargs={"token": token})).status_code
        == 400
    )
    assert not Membership.objects.filter(user=other_user, workspace=business_ws).exists()


def test_aceptar_requiere_sesion(client):
    response = client.get(reverse("workspaces:accept_invitation", kwargs={"token": "x"}))
    assert response.status_code == 302 and reverse("account_login") in response["Location"]


def test_carrera_al_aceptar(client, user, business_ws, carla, monkeypatch):
    """Si la invitación se usa entre la vista y el servicio, se muestra el problema."""
    _, token = invitar(business_ws, user)
    client.force_login(carla)

    def falla(*a, **k):
        raise ValidationError("Esta invitación ya se usó.")

    monkeypatch.setattr("apps.workspaces.team_views.accept_invitation", falla)
    response = client.post(reverse("workspaces:accept_invitation", kwargs={"token": token}))
    assert response.status_code == 400 and "ya se usó" in response.content.decode()


# --- Lo que ve el vendedor -------------------------------------------------------------------


@pytest.fixture
def vendedora(user, business_ws, carla):
    Membership.objects.create(user=carla, workspace=business_ws, role=VENDEDOR)
    Product.objects.create(
        workspace=business_ws, name="Bizcocho", price=D("1000"), unit_cost=D("613.47"),
        tracks_inventory=True, stock_minimum=D("5"),
    )  # fmt: skip
    return carla


def vender(ws, quien, **kw):
    caja = Account.objects.get(workspace=ws, name="Efectivo")
    data = {
        "client_uuid": str(uuid.uuid4()),
        "date": timezone.localdate().isoformat(),
        "payment": "contado",
        "account": str(caja.pk),
        "producto_1": str(Product.objects.get(name="Bizcocho").pk),
        "cantidad_1": "1",
        **kw,
    }
    return data


def test_vendedor_vende_sin_ver_costos(client, business_ws, vendedora, user):
    client.force_login(vendedora)
    u = lambda name, **kw: reverse(f"business:{name}", kwargs={"ws": business_ws.pk, **kw})  # noqa: E731
    response = client.post(u("sale_new"), vender(business_ws, vendedora))
    sale = Sale.objects.get()
    assert response["Location"] == u("sale_detail", sale_id=sale.pk)
    assert sale.created_by == vendedora
    detail = client.get(u("sale_detail", sale_id=sale.pk)).content.decode()
    assert "613.47" not in detail and "Ganancia" not in detail and "Anular" not in detail
    assert "Registrada por" in detail

    inicio = client.get(reverse("espacio:dashboard", kwargs={"ws": business_ws.pk}))
    html = inicio.content.decode()
    assert "Vendido por ti" in html and "RD$1,000.00" in html
    assert "Ganancia" not in html and "Margen" not in html and "Por agotarse" in html
    assert "Movimientos" not in html  # menú del vendedor

    inv = client.get(u("inventory")).content.decode()
    assert "613.47" not in inv and "costo promedio" not in inv and "precio" in inv

    # Cobros: puede cobrar, pero no registrar deudas antiguas.
    credito = vender(business_ws, vendedora, payment="credito", account="",
                     customer_name="Pedro", due_date="2026-12-01")  # fmt: skip
    client.post(u("sale_new"), credito)
    debt = Receivable.objects.get()
    page = client.get(u("receivables")).content.decode()
    assert "Pedro" in page and "Registrar algo que te deben" not in page
    assert client.post(u("receivables"), {"concept": "Vieja", "amount": "5"}).status_code == 404
    caja = Account.objects.get(workspace=business_ws, name="Efectivo")
    client.post(
        u("collect", debt_id=debt.pk),
        {"amount": "1000", "account": str(caja.pk), "date": timezone.localdate().isoformat(),
         "client_uuid": str(uuid.uuid4())},
    )  # fmt: skip
    debt.refresh_from_db()
    assert debt.paid == D("1000.00")

    # El propietario sí ve el costo de la venta de la vendedora.
    client.force_login(user)
    assert "Ganancia" in client.get(u("sale_detail", sale_id=sale.pk)).content.decode()


def test_vendedor_sin_productos_vuelve_al_inicio(client, business_ws, carla):
    Membership.objects.create(user=carla, workspace=business_ws, role=VENDEDOR)
    client.force_login(carla)
    response = client.get(reverse("business:sale_new", kwargs={"ws": business_ws.pk}))
    assert response["Location"] == reverse("espacio:dashboard", kwargs={"ws": business_ws.pk})


def test_admin_no_borra_retiros_del_propietario(client, user, business_ws, personal_ws, carla):
    Membership.objects.create(user=carla, workspace=business_ws, role=ADMIN)
    caja = lambda ws: Account.objects.get(workspace=ws, name="Efectivo")  # noqa: E731
    t, _ = transfer_between(user, business_ws, personal_ws, "500", timezone.localdate(),
                            WorkspaceTransfer.Kind.RETIRO_PROPIETARIO, caja(business_ws),
                            caja(personal_ws))  # fmt: skip
    client.force_login(carla)
    url = reverse("ledger:delete", kwargs={"ws": business_ws.pk, "tx_id": t.out_tx.pk})
    response = client.post(url, follow=True)
    assert WorkspaceTransfer.objects.exists()
    assert "propietario" in response.content.decode().lower()


def test_venta_por_servicio_registra_quien(business_ws, vendedora):
    sale, _ = register_sale(
        business_ws,
        vendedora,
        SaleData(
            date=timezone.localdate(),
            account=Account.objects.get(workspace=business_ws, name="Efectivo"),
            lines=[SaleLineData(product=Product.objects.get(name="Bizcocho"), qty=D("1"))],
        ),
    )
    assert sale.created_by == vendedora
