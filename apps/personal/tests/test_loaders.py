from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.ledger.choices import Direction, TxKind
from apps.ledger.models import Account, Category
from apps.ledger.services.recording import (
    TxData,
    create_account,
    record_transaction,
    record_transfer,
)
from apps.personal.models import (
    Commitment,
    Debt,
    EssentialEstimate,
    IncomeSource,
    Preference,
    SavingsGoal,
)
from apps.personal.services.loaders import (
    current_plan,
    historical_essentials,
    load_incomes,
    load_personal_inputs,
    workspace_availability,
)
from apps.personal.services.types import PlanStatus, Priority

from .data import load_caso_50000

pytestmark = pytest.mark.django_db
D = Decimal
HOY = date(2026, 10, 10)


def cat(ws, name):
    return Category.objects.for_workspace(ws).get(name=name)


@pytest.fixture
def caso(personal_ws):
    """El caso RD$50,000 cargado en la base de datos."""
    return load_caso_50000(personal_ws)


def test_plan_desde_la_base_de_datos(caso):
    plan = current_plan(caso, HOY)
    assert plan.status == PlanStatus.VIABLE
    assert plan.totals_by_kind["compromiso"] == D("20000")
    assert plan.totals_by_kind["esencial"] == D("15000")
    assert plan.totals_by_kind["ahorro"] == D("7000")
    assert plan.totals_by_kind["discrecional"] == D("5000")
    assert plan.totals_by_kind["reserva"] == D("3000")
    inputs = load_personal_inputs(caso, HOY)
    assert inputs.preferences == {str(cat(caso, "Alimentación").pk): Priority.REDUCIBLE}
    # El ahorro sin categoría usa la categoría del sistema "Ahorro".
    assert inputs.savings[0].category_ref == str(cat(caso, "Ahorro").pk)


def test_sin_perfil_usa_valores_por_defecto(personal_ws):
    inputs = load_personal_inputs(personal_ws, HOY)
    assert inputs.discretionary_wish is None
    assert inputs.reserve_pct == D("0.10")
    assert inputs.period.start == date(2026, 10, 1)
    assert load_incomes(personal_ws) == []


def test_deuda_usa_categoria_de_prestamos(caso):
    Debt.objects.create(
        workspace=caso, name="Préstamo", installment=4000, balance=20000, due_day=10
    )
    (debt,) = load_personal_inputs(caso, HOY).debts
    assert debt.category_ref == str(cat(caso, "Préstamos y deudas").pk)


def _gasto(ws, user, account, category, amount, on):
    record_transaction(
        ws,
        user,
        TxData(
            account=account,
            date=on,
            amount=D(amount),
            direction=Direction.OUT,
            kind=TxKind.GASTO,
            category=category,
        ),
    )


def test_promedio_del_historial_con_dos_periodos_completos(caso, user):
    efectivo = Account.objects.for_workspace(caso).get(name="Efectivo")
    comida = cat(caso, "Alimentación")
    assert (
        historical_essentials(caso, load_incomes(caso), load_personal_inputs(caso, HOY).period)
        is None
    )
    _gasto(caso, user, efectivo, comida, "11000", date(2026, 8, 1))
    _gasto(caso, user, efectivo, comida, "13000", date(2026, 9, 15))
    _gasto(caso, user, efectivo, cat(caso, "Ocio y salidas"), "999", date(2026, 9, 15))
    inputs = load_personal_inputs(caso, HOY)
    by_ref = {e.category_ref: e for e in inputs.essentials}
    comida_input = by_ref[str(comida.pk)]
    assert (comida_input.amount, comida_input.from_history) == (D("12000.00"), True)
    transporte = by_ref[str(cat(caso, "Transporte y combustible").pk)]
    assert (transporte.amount, transporte.from_history) == (D("5000"), False)
    assert str(cat(caso, "Ocio y salidas").pk) not in by_ref


def test_historial_incompleto_usa_estimado(caso, user):
    efectivo = Account.objects.for_workspace(caso).get(name="Efectivo")
    _gasto(caso, user, efectivo, cat(caso, "Alimentación"), "13000", date(2026, 9, 15))
    assert all(not e.from_history for e in load_personal_inputs(caso, HOY).essentials)


def test_ahorro_previo_cuenta_para_la_meta(caso, user):
    goal = SavingsGoal.objects.for_workspace(caso).get()
    goal.target_amount = D("10000")
    goal.saved_initial = D("1000")
    goal.save()
    banco = create_account(caso, "Banco", "banco", "20000")
    ahorro = create_account(caso, "Ahorro", "banco")
    record_transfer(
        caso,
        user,
        from_account=banco,
        to_account=ahorro,
        amount="4000",
        on=date(2026, 9, 20),
        category=cat(caso, "Ahorro"),
    )
    (savings,) = load_personal_inputs(caso, HOY).savings
    assert savings.saved_so_far == D("5000")
    # Solo faltan 5,000 para la meta: el plan no aporta más que eso.
    assert current_plan(caso, HOY).totals_by_kind["ahorro"] == D("5000")


def test_disponible_real(caso, user):
    banco = create_account(caso, "Banco", "banco")
    ahorro = create_account(caso, "Ahorro", "banco", is_savings=True)
    record_transaction(
        caso,
        user,
        TxData(
            account=banco,
            date=date(2026, 10, 1),
            amount=D("50000"),
            direction=Direction.IN,
            kind=TxKind.INGRESO,
            category=cat(caso, "Salario"),
        ),
    )
    _gasto(caso, user, banco, cat(caso, "Alquiler o hipoteca"), "15000", date(2026, 10, 5))
    _gasto(caso, user, banco, cat(caso, "Alimentación"), "2000", date(2026, 10, 6))
    record_transfer(
        caso,
        user,
        from_account=banco,
        to_account=ahorro,
        amount="7000",
        on=date(2026, 10, 2),
        category=cat(caso, "Ahorro"),
    )
    a = workspace_availability(caso, HOY)
    assert a.in_accounts == D("33000")  # la cuenta de ahorro sigue siendo tuya
    assert a.pending_commitments == D("5000")
    assert a.pending_savings == 0
    assert a.reserves == D("3000")
    assert a.in_savings_accounts == D("7000")
    # 33,000 en cuentas − 7,000 en la cuenta de ahorro − 5,000 pendientes − 3,000 de reserva.
    assert a.spendable == D("18000")


def test_ahorro_en_cuenta_de_ahorro_no_es_gastable(caso, user):
    create_account(caso, "Ahorros", "banco", "100000", is_savings=True)
    a = workspace_availability(caso, HOY)
    assert a.in_accounts == D("100000")
    assert a.for_spending == 0


def test_validaciones_de_modelos(personal_ws, other_ws):
    ingreso = IncomeSource(
        workspace=personal_ws, name="X", net_amount=1, frequency="quincenal", pay_days=[15]
    )
    with pytest.raises(ValidationError):
        ingreso.full_clean()
    compromiso = Commitment(
        workspace=personal_ws, name="X", amount=1, due_day=32, category=cat(other_ws, "Agua")
    )
    with pytest.raises(ValidationError) as exc:
        compromiso.full_clean()
    assert {"due_day", "category"} <= set(exc.value.message_dict)
    semanal = Commitment(
        workspace=personal_ws,
        name="X",
        amount=1,
        frequency="semanal",
        due_day=7,
        category=cat(personal_ws, "Agua"),
    )
    with pytest.raises(ValidationError):
        semanal.full_clean()
    meta = SavingsGoal(
        workspace=personal_ws,
        purpose="X",
        contribution_amount=1,
        contribution_frequency="diaria",
        daily_mode="dias_seleccionados",
    )
    with pytest.raises(ValidationError):
        meta.full_clean()
    assert str(ingreso) == "X" and str(meta) == "X"


def test_str(caso):
    assert str(Commitment.objects.for_workspace(caso).first()) == "Alquiler"
    comida = EssentialEstimate.objects.for_workspace(caso).get(category__name="Alimentación")
    assert str(comida) == "Alimentación · 10000.00"
    assert str(Preference.objects.for_workspace(caso).get()) == "Alimentación: reducible"
    debt = Debt.objects.create(workspace=caso, name="Tarjeta", installment=1, balance=1, due_day=1)
    assert str(debt) == "Tarjeta"
