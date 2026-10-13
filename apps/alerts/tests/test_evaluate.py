from datetime import date
from decimal import Decimal

import pytest

from apps.alerts.models import Alert, AlertRule
from apps.alerts.services.evaluate import evaluate_workspace, purchase_warnings
from apps.alerts.tasks import evaluate_all_task
from apps.ledger.choices import Direction, TxKind, TxStatus
from apps.ledger.models import Account
from apps.ledger.services.recording import TxData, create_account, record_transaction
from apps.personal.tests.data import cat, load_caso_50000
from apps.planning.services.generate import request_personal_plan
from apps.planning.services.lifecycle import accept_plan

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture
def caso(personal_ws):
    return load_caso_50000(personal_ws)


def gasto(ws, user, account, category, amount, on, status=TxStatus.CONFIRMADO, kind=TxKind.GASTO):
    return record_transaction(
        ws,
        user,
        TxData(
            account=account,
            date=on,
            amount=D(amount),
            direction=Direction.OUT if kind != TxKind.INGRESO else Direction.IN,
            kind=kind,
            category=category,
            status=status,
        ),
    )


def by_code(ws):
    return {a.code: a for a in Alert.objects.for_workspace(ws)}


def test_evalua_y_no_duplica(caso, user):
    banco = create_account(caso, "Banco", "banco", "1000")
    gasto(caso, user, banco, cat(caso, "Alimentación"), "800", date(2026, 10, 2))
    first = evaluate_workspace(caso, date(2026, 10, 13))
    assert {a.code for a in first} >= {
        "pago_sin_cobertura",
        "meta_en_riesgo",
        "compra_afecta_reserva",
    }
    evaluate_workspace(caso, date(2026, 10, 13))
    assert Alert.objects.for_workspace(caso).count() == len(first)
    alert = by_code(caso)["pago_sin_cobertura"]
    assert alert.status == "nueva" and alert.period_start == date(2026, 10, 1)
    assert str(alert) == alert.title


def test_se_resuelve_sola_y_reaparece(caso, user):
    banco = create_account(caso, "Banco", "banco", "1000")
    evaluate_workspace(caso, date(2026, 10, 13))
    assert by_code(caso)["pago_sin_cobertura"].is_open
    gasto(caso, user, banco, cat(caso, "Electricidad"), "2500", date(2026, 10, 13))
    evaluate_workspace(caso, date(2026, 10, 13))
    alert = by_code(caso)["pago_sin_cobertura"]
    assert alert.status == "resuelta" and alert.resolved_at
    # Si la situación vuelve (p. ej. se anula el pago), la alerta se reabre.
    from apps.ledger.models import Transaction

    Transaction.objects.for_workspace(caso).filter(category=cat(caso, "Electricidad")).delete()
    evaluate_workspace(caso, date(2026, 10, 13))
    assert by_code(caso)["pago_sin_cobertura"].status == "nueva"


def test_descartada_no_vuelve(caso):
    create_account(caso, "Banco", "banco", "1000")
    evaluate_workspace(caso, date(2026, 10, 13))
    Alert.objects.for_workspace(caso).filter(code="meta_en_riesgo").update(status="descartada")
    evaluate_workspace(caso, date(2026, 10, 14))
    assert by_code(caso)["meta_en_riesgo"].status == "descartada"


def test_sin_ingresos_o_negocio_no_evalua(personal_ws, business_ws):
    assert evaluate_workspace(personal_ws, date(2026, 10, 13)) == []
    assert evaluate_workspace(business_ws, date(2026, 10, 13)) == []


def test_usa_el_plan_aceptado(caso, user, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        plan = request_personal_plan(caso, user, date(2026, 10, 10))
    plan.refresh_from_db()
    accept_plan(plan, user)
    alerts = evaluate_workspace(caso, date(2026, 10, 13))
    assert alerts and all(a.data_used["plan"] == "aceptado" for a in alerts)


def test_reglas_desactivadas_por_el_usuario(caso):
    for code in ["pago_sin_cobertura", "meta_en_riesgo", "compra_afecta_reserva"]:
        AlertRule.objects.create(workspace=caso, code=code, enabled=False)
    assert evaluate_workspace(caso, date(2026, 10, 13)) == []
    assert str(AlertRule.objects.for_workspace(caso).first()).endswith("(inactiva)")


def test_movimiento_confirmado_dispara_la_evaluacion(
    caso, user, django_capture_on_commit_callbacks
):
    efectivo = Account.objects.for_workspace(caso).get(name="Efectivo")
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        gasto(
            caso,
            user,
            efectivo,
            cat(caso, "Alimentación"),
            "100",
            date(2026, 10, 2),
            status=TxStatus.PENDIENTE_REVISION,
        )
    assert callbacks == []  # un borrador no dispara alertas
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        gasto(caso, user, efectivo, cat(caso, "Alimentación"), "100", date(2026, 10, 2))
    assert len(callbacks) == 1
    assert Alert.objects.for_workspace(caso).exists()


def test_evaluacion_diaria(caso, business_ws, other_ws):
    assert evaluate_all_task() == 3  # personales y de negocio
    from apps.alerts.tasks import evaluate_workspace_task

    evaluate_workspace_task("00000000-0000-0000-0000-000000000000")  # inexistente: no falla


def test_avisos_previos(caso, business_ws, personal_ws):
    create_account(caso, "Banco", "banco", "500")
    warnings = purchase_warnings(caso, D("2000"), cat(caso, "Alimentación"), date(2026, 10, 13))
    assert warnings[0].code == "compra_afecta_reserva"
    assert purchase_warnings(business_ws, D("1"), None) == []


def test_avisos_previos_sin_plan(personal_ws):
    assert purchase_warnings(personal_ws, D("1"), None, date(2026, 10, 13)) == []
