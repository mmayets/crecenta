import pytest

from apps.ledger.models import Account
from apps.onboarding.services.steps import (
    completeness,
    get_state,
    next_step,
    previous_step,
)
from apps.personal.tests.data import load_caso_50000

pytestmark = pytest.mark.django_db


def test_perfil_vacio(personal_ws):
    progress = completeness(personal_ws)
    assert progress.percent == 0
    assert not progress.minimum_ready
    assert [s.step.key for s in progress.missing][:3] == ["ingresos", "compromisos", "esenciales"]
    assert str(get_state(personal_ws)) == "Bienvenida de Mis finanzas"


def test_caso_completo_minimo(personal_ws):
    load_caso_50000(personal_ws)
    progress = completeness(personal_ws)
    assert progress.minimum_ready
    # ingresos 30 + compromisos 15 + esenciales 20 + ahorro 10 + preferencias 10 = 85
    assert progress.percent == 85
    assert {s.step.key for s in progress.missing} == {"cuentas", "deudas"}


def test_responder_sin_datos_cuenta_omitir_no(personal_ws):
    state = get_state(personal_ws)
    state.mark("deudas")  # "no tengo deudas"
    state.mark("cuentas", skipped=True)
    state.save()
    progress = {s.step.key: s for s in completeness(personal_ws).steps}
    assert progress["deudas"].done and not progress["deudas"].skipped
    assert not progress["cuentas"].done and progress["cuentas"].skipped
    state.mark("cuentas")  # luego lo responde
    assert "cuentas" not in state.skipped_steps


def test_saldo_cuenta_como_dato(personal_ws):
    Account.objects.for_workspace(personal_ws).update(opening_balance=500)
    assert {s.step.key for s in completeness(personal_ws).steps if s.done} == {"cuentas"}


def test_navegacion():
    assert next_step("ingresos") == "compromisos"
    assert next_step("preferencias") is None
    assert previous_step("ingresos") is None
    assert previous_step("compromisos") == "ingresos"
