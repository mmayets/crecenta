import pytest
from django.urls import reverse

from apps.workspaces.mixins import SESSION_KEY
from apps.workspaces.models import Workspace

pytestmark = pytest.mark.django_db


def test_inicio_sin_espacios_abre_el_asistente(client, user):
    client.force_login(user)
    response = client.get(reverse("home"))
    assert response["Location"] == reverse("asistente:first_space")


def test_inicio_anonimo_ve_la_pagina_publica_con_precios(client):
    response = client.get(reverse("home"))
    html = response.content.decode()
    assert response.status_code == 200
    assert "RD$199" in html and "RD$449" in html and "RD$1,990" in html
    assert reverse("account_login") in html and reverse("account_signup") in html


def test_la_pwa_instalada_abre_el_login(client):
    response = client.get(reverse("home"), {"origen": "pwa"})
    assert response["Location"] == reverse("account_login")


def test_elegir_uso_crea_espacios(client, user):
    client.force_login(user)
    page = client.get(reverse("workspaces:usage"))
    assert "¿Para qué usarás la app?" in page.content.decode()
    response = client.post(
        reverse("workspaces:usage"),
        {"usage": "ambos", "currency": "DOP", "business_name": "Dulces Ana"},
    )
    personal = Workspace.objects.get(owner=user, kind="personal")
    # Un espacio personal nuevo continúa con el onboarding.
    assert response["Location"] == reverse("onboarding:index", kwargs={"ws": personal.pk})
    assert Workspace.objects.get(owner=user, kind="business").name == "Dulces Ana"


def test_elegir_solo_negocio_va_al_tablero(client, user):
    client.force_login(user)
    response = client.post(reverse("workspaces:usage"), {"usage": "negocio", "currency": "USD"})
    negocio = Workspace.objects.get(owner=user, kind="business")
    assert response["Location"] == reverse("espacio:dashboard", kwargs={"ws": negocio.pk})


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
