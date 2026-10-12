import pytest
from django.urls import reverse

from apps.workspaces.mixins import SESSION_KEY
from apps.workspaces.models import Workspace

pytestmark = pytest.mark.django_db


def test_inicio_sin_espacios_pide_uso(client, user):
    client.force_login(user)
    response = client.get(reverse("home"))
    assert response["Location"] == reverse("workspaces:usage")


def test_inicio_anonimo_va_a_login(client):
    response = client.get(reverse("home"))
    assert reverse("account_login") in response["Location"]


def test_elegir_uso_crea_espacios(client, user):
    client.force_login(user)
    page = client.get(reverse("workspaces:usage"))
    assert "¿Para qué usarás la app?" in page.content.decode()
    response = client.post(
        reverse("workspaces:usage"),
        {"usage": "ambos", "currency": "DOP", "business_name": "Dulces Ana"},
    )
    personal = Workspace.objects.get(owner=user, kind="personal")
    assert response["Location"] == reverse("espacio:dashboard", kwargs={"ws": personal.pk})
    assert Workspace.objects.get(owner=user, kind="business").name == "Dulces Ana"


def test_elegir_uso_repetido_redirige_al_existente(client, user, personal_ws):
    client.force_login(user)
    response = client.post(reverse("workspaces:usage"), {"usage": "persona", "currency": "DOP"})
    assert response["Location"] == reverse("espacio:dashboard", kwargs={"ws": personal_ws.pk})


def test_elegir_uso_invalido(client, user):
    client.force_login(user)
    response = client.post(reverse("workspaces:usage"), {"usage": "x", "currency": "DOP"})
    assert response.status_code == 200
    assert not Workspace.objects.filter(owner=user).exists()


def test_inicio_abre_ultimo_espacio_usado(client, user, personal_ws, business_ws):
    client.force_login(user)
    client.get(reverse("espacio:dashboard", kwargs={"ws": business_ws.pk}))
    assert client.session[SESSION_KEY] == str(business_ws.pk)
    response = client.get(reverse("home"))
    assert response["Location"] == reverse("espacio:dashboard", kwargs={"ws": business_ws.pk})


def test_tablero_muestra_promesa_segun_tipo(client, user, personal_ws, business_ws):
    client.force_login(user)
    personal = client.get(reverse("espacio:dashboard", kwargs={"ws": personal_ws.pk}))
    assert "Organiza tu dinero" in personal.content.decode()
    negocio = client.get(reverse("espacio:dashboard", kwargs={"ws": business_ws.pk}))
    html = negocio.content.decode()
    assert "Conoce tus costos" in html
    assert "Dulces Ana · Negocio" in html


def test_selector_solo_muestra_espacios_propios(client, user, personal_ws, other_ws):
    client.force_login(user)
    html = client.get(reverse("workspaces:selector")).content.decode()
    assert str(personal_ws.pk) in html
    assert str(other_ws.pk) not in html


def test_selector_vacio(client, user):
    client.force_login(user)
    assert (
        "Todavía no tienes espacios" in client.get(reverse("workspaces:selector")).content.decode()
    )


def test_str_membresia(user, personal_ws):
    from apps.workspaces.models import Membership

    assert str(Membership.objects.get(workspace=personal_ws)) == "ana@example.com · Mis finanzas"
