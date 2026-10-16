from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.ledger.choices import AccountType, Direction, TxKind, TxSource
from apps.ledger.models import Account, Category, Transaction
from apps.ledger.services.recording import TxData, create_account, record_transaction
from apps.personal.models import Commitment, IncomeSource, PersonalProfile
from apps.personal.services.auto_record import record_due, record_due_all

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture
def bank(personal_ws):
    return create_account(personal_ws, "Cuenta bancaria", AccountType.BANCO, "1000")


@pytest.fixture
def setup(personal_ws, bank):
    """Cobra RD$25,000 el 15 y el 30; paga luz fija el 10 y agua variable el 12."""
    IncomeSource.objects.create(
        workspace=personal_ws, name="Sueldo", net_amount=D("25000"), frequency="quincenal",
        pay_days=[15, 30],
    )  # fmt: skip
    category = lambda name: Category.objects.for_workspace(personal_ws).get(name=name)  # noqa: E731
    Commitment.objects.create(workspace=personal_ws, name="Luz", category=category("Electricidad"),
                              amount=D("2500"), due_day=10)  # fmt: skip
    Commitment.objects.create(workspace=personal_ws, name="Agua", category=category("Agua"),
                              amount=D("500"), due_day=12, is_fixed=False)  # fmt: skip
    PersonalProfile.objects.create(
        workspace=personal_ws, auto_record=True, auto_account=bank, auto_since=date(2026, 10, 1)
    )
    return personal_ws


def auto(ws):
    return Transaction.objects.for_workspace(ws).filter(source=TxSource.AUTOMATICO)


def test_anota_cobros_y_pagos_fijos_en_su_fecha(setup, bank):
    assert record_due(setup, date(2026, 10, 15)) == 2
    rows = sorted(auto(setup).values_list("date", "direction", "amount", "description"))
    assert rows == [
        (date(2026, 10, 10), Direction.OUT, D("2500"), "Luz"),
        (date(2026, 10, 15), Direction.IN, D("25000"), "Sueldo"),
    ]
    assert set(auto(setup).values_list("account", flat=True)) == {bank.pk}
    salary = auto(setup).get(direction=Direction.IN)
    assert (salary.kind, salary.category.name) == (TxKind.INGRESO, "Salario")
    # El agua varía cada mes: nunca se anota sola.
    assert not auto(setup).filter(description="Agua").exists()


def test_correr_dos_veces_no_duplica(setup):
    record_due(setup, date(2026, 10, 15))
    assert record_due(setup, date(2026, 10, 15)) == 0
    assert record_due_all(date(2026, 10, 15)) == 0
    assert auto(setup).count() == 2


def test_no_llena_fechas_antes_de_activarlo(setup):
    PersonalProfile.objects.filter(workspace=setup).update(auto_since=date(2026, 10, 14))
    record_due(setup, date(2026, 10, 15))
    assert list(auto(setup).values_list("description", flat=True)) == ["Sueldo"]


def test_solo_mira_una_semana_atras(setup):
    PersonalProfile.objects.filter(workspace=setup).update(auto_since=date(2026, 1, 1))
    record_due(setup, date(2026, 10, 31))  # el 10 quedó fuera; el 30 no
    assert list(auto(setup).values_list("date", flat=True)) == [date(2026, 10, 30)]


def test_no_repite_lo_que_ya_anoto_a_mano(setup, bank):
    luz = Category.objects.for_workspace(setup).get(name="Electricidad")
    record_transaction(setup, None, TxData(account=bank, date=date(2026, 10, 8), amount=D("2600"),
                                           direction=Direction.OUT, kind=TxKind.GASTO,
                                           category=luz))  # fmt: skip
    record_due(setup, date(2026, 10, 15))
    assert list(auto(setup).values_list("description", flat=True)) == ["Sueldo"]


def test_apagado_no_anota_nada(setup):
    PersonalProfile.objects.filter(workspace=setup).update(auto_record=False)
    assert record_due(setup, date(2026, 10, 15)) == 0


def test_sin_cuenta_elegida_usa_la_primera(setup):
    PersonalProfile.objects.filter(workspace=setup).update(auto_account=None)
    record_due(setup, date(2026, 10, 15))
    efectivo = Account.objects.for_workspace(setup).get(name="Efectivo")
    assert set(auto(setup).values_list("account", flat=True)) == {efectivo.pk}


def test_compromiso_anual_solo_en_su_mes(personal_ws, bank):
    seguro = Category.objects.for_workspace(personal_ws).get(name="Seguros")
    Commitment.objects.create(workspace=personal_ws, name="Marbete", category=seguro,
                              amount=D("3000"), frequency="anual", due_day=5,
                              due_month=11)  # fmt: skip
    PersonalProfile.objects.create(workspace=personal_ws, auto_record=True, auto_account=bank,
                                   auto_since=date(2026, 1, 1))  # fmt: skip
    assert record_due(personal_ws, date(2026, 10, 6)) == 0
    assert record_due(personal_ws, date(2026, 11, 6)) == 1


def test_el_panel_anota_lo_del_dia(client, user, setup):
    today = timezone.localdate()
    IncomeSource.objects.for_workspace(setup).update(frequency="mensual", pay_days=[today.day])
    PersonalProfile.objects.filter(workspace=setup).update(auto_since=today)
    client.force_login(user)
    client.get(reverse("espacio:dashboard", kwargs={"ws": setup.pk}))
    assert auto(setup).filter(date=today, description="Sueldo").exists()  # sin esperar a beat


def test_ajustes_enciende_y_apaga(client, user, personal_ws, bank):
    client.force_login(user)
    url = reverse("espacio:settings", kwargs={"ws": personal_ws.pk})
    assert 'data-testid="registro-automatico"' in client.get(url).content.decode()
    client.post(url, {"auto_record": "on", "auto_account": str(bank.pk)})
    profile = PersonalProfile.objects.get(workspace=personal_ws)
    assert profile.auto_record and profile.auto_account == bank and profile.auto_since
    client.post(url, {"auto_account": str(bank.pk)})
    profile.refresh_from_db()
    assert not profile.auto_record
