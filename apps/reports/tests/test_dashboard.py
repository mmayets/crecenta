import json
from datetime import date
from decimal import Decimal
from unittest import mock

import pytest
from django.urls import reverse

from apps.ledger.choices import Direction, TxKind
from apps.ledger.services.recording import (
    TxData,
    create_account,
    record_transaction,
    record_transfer,
)
from apps.personal.tests.data import cat, load_caso_50000
from apps.reports.services.dashboard import Bar, build_personal_dashboard

pytestmark = pytest.mark.django_db
D = Decimal
HOY = date(2026, 10, 10)


def mov(ws, user, account, category, amount, on, kind=TxKind.GASTO):
    return record_transaction(
        ws,
        user,
        TxData(
            account=account,
            date=on,
            amount=D(amount),
            direction=Direction.IN if kind == TxKind.INGRESO else Direction.OUT,
            kind=kind,
            category=category,
        ),
    )


@pytest.fixture
def caso(personal_ws, user):
    load_caso_50000(personal_ws)
    banco = create_account(personal_ws, "Banco", "banco")
    ahorro = create_account(personal_ws, "Ahorro", "banco", is_savings=True)
    mov(
        personal_ws,
        user,
        banco,
        cat(personal_ws, "Salario"),
        "50000",
        date(2026, 10, 1),
        TxKind.INGRESO,
    )
    mov(
        personal_ws,
        user,
        banco,
        cat(personal_ws, "Alquiler o hipoteca"),
        "15000",
        date(2026, 10, 5),
    )
    mov(personal_ws, user, banco, cat(personal_ws, "Alimentación"), "4000", date(2026, 10, 6))
    mov(personal_ws, user, banco, cat(personal_ws, "Ocio y salidas"), "1000", date(2026, 10, 7))
    record_transfer(
        personal_ws,
        user,
        from_account=banco,
        to_account=ahorro,
        amount="7000",
        on=date(2026, 10, 2),
        category=cat(personal_ws, "Ahorro"),
    )
    return personal_ws


def test_inicio_con_plan(caso):
    d = build_personal_dashboard(caso, HOY)
    assert d.ready and d.plan_source == "calculado" and d.plan_status == "viable"
    assert d.days_left == 22
    a = d.availability
    assert (a.in_accounts, a.in_savings_accounts) == (D("30000"), D("7000"))
    # 23,000 de uso diario − 5,000 (luz e internet) − 0 ahorro − 3,000 reserva
    assert a.spendable == D("15000")
    bars = {b.label: b for b in d.bars}
    assert (bars["Compromisos y deudas"].used, bars["Compromisos y deudas"].assigned) == (
        D("15000"),
        D("20000"),
    )
    assert bars["Alimentación"].percent == 40
    assert bars["Ocio y gastos personales"].used == D("1000")
    assert bars["Ahorro"].used == D("7000")
    assert [(u.name, u.date) for u in d.upcoming] == [
        ("Electricidad", date(2026, 10, 15)),
        ("Internet", date(2026, 10, 20)),
    ]
    assert d.spending_by_group == {
        "Compromisos": D("15000.00"),
        "Esenciales": D("4000.00"),
        "Ocio": D("1000.00"),
    }


def test_inicio_sin_ingresos(personal_ws):
    d = build_personal_dashboard(personal_ws, HOY)
    assert not d.ready and d.profile.percent == 0 and d.bars == []


def test_barras():
    assert Bar("x", D("100"), D("150"), "esencial").over
    assert Bar("x", D("0"), D("5"), "esencial").percent == 100
    assert Bar("x", D("0"), D("0"), "esencial").percent == 0
    assert Bar("x", D("100"), D("30"), "esencial").left == D("70")


def test_vista_de_inicio(client, user, caso):
    client.force_login(user)
    with mock.patch("apps.workspaces.views.timezone.localdate", return_value=HOY):
        html = client.get(reverse("espacio:dashboard", kwargs={"ws": caso.pk})).content.decode()
    assert "Disponible en tus cuentas" in html and "Disponible para gastar" in html
    assert 'data-testid="para-gastar">RD$15,000.00' in html
    assert "Próximos pagos" in html and "Electricidad" in html
    assert 'id="datos-grafico"' in html
    data = html.split('id="datos-grafico" type="application/json">')[1].split("</script>")[0]
    assert json.loads(data)["labels"] == ["Compromisos", "Esenciales", "Ocio"]
    assert "Aún no has aceptado un plan" in html
    assert '<use href="#i-wallet">' in html


def test_vista_sin_datos_y_negocio(client, user, personal_ws, business_ws):
    client.force_login(user)
    html = client.get(reverse("espacio:dashboard", kwargs={"ws": personal_ws.pk})).content.decode()
    assert "Completar mi perfil" in html
    html = client.get(reverse("espacio:dashboard", kwargs={"ws": business_ws.pk})).content.decode()
    assert "¿Cuánto gané?" in html and "Conoce tus costos" in html
    assert "Comprobantes" in html  # navegación de negocio


def test_ajustes(client, user, personal_ws):
    client.force_login(user)
    html = client.get(reverse("espacio:settings", kwargs={"ws": personal_ws.pk})).content.decode()
    assert "Configuración y privacidad" in html and "Categorías" in html
