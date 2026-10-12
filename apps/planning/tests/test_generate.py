import json
from datetime import date
from unittest import mock

import pytest

from apps.ai.models import AIInteraction
from apps.ai.providers import FakeProvider
from apps.ai.schemas import PlanNarrative
from apps.ai.services.guards import verify_narrative
from apps.ledger.services.recording import create_account
from apps.personal.models import IncomeSource
from apps.personal.services.serialize import strip_refs
from apps.personal.tests.data import load_caso_50000
from apps.planning.models import PlanVersion
from apps.planning.services import generate
from apps.planning.services.generate import narrate_plan, request_personal_plan
from apps.planning.services.missing_data import compute_missing_data

pytestmark = pytest.mark.django_db
HOY = date(2026, 10, 10)


@pytest.fixture
def caso(personal_ws):
    return load_caso_50000(personal_ws)


def generar(ws, user, capture, **kw):
    with capture(execute=True):
        plan = request_personal_plan(ws, user, HOY, **kw)
    plan.refresh_from_db()
    return plan


def assert_cifras_del_motor(plan):
    narrative = PlanNarrative.model_validate(plan.ai_narrative)
    assert verify_narrative(narrative, strip_refs(plan.computed)) == []


def test_calcula_guarda_y_explica(caso, user, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks() as callbacks:
        plan = request_personal_plan(caso, user, HOY)
    assert plan.status == PlanVersion.Status.GENERANDO
    assert plan.plan_status == "viable"
    assert plan.computed["totales"]["reserva"] == "3000.00"
    assert plan.period_start == date(2026, 10, 1)
    assert len(callbacks) == 1  # la explicación se encola al confirmar la transacción
    callbacks[0]()
    plan.refresh_from_db()
    assert plan.status == PlanVersion.Status.PROPUESTA
    assert plan.narrative_source == "reglas"  # sin consentimiento de IA
    assert_cifras_del_motor(plan)
    assert str(plan).startswith("Plan 01/10/2026")


def test_snapshot_y_prompt_sin_datos_de_cuentas_ni_de_la_persona(
    caso, user, django_capture_on_commit_callbacks
):
    user.set_ai_consent(True)
    create_account(caso, "Banco Popular 123-456789-0", "banco", "15000")
    plan = generar(caso, user, django_capture_on_commit_callbacks)
    stored = json.dumps(plan.inputs_snapshot) + json.dumps(plan.computed)
    assert "Banco Popular" not in stored and "123-456789-0" not in stored
    prompt = FakeProvider.calls[0]["system"] + FakeProvider.calls[0]["user"]
    assert "Banco Popular" not in prompt and "123-456789" not in prompt
    assert user.email not in prompt
    assert '"ref"' not in prompt and str(caso.pk) not in prompt
    assert "Alimentación" in prompt  # las preferencias van con el nombre de la categoría
    assert plan.narrative_source == "ia"
    assert plan.ai_interaction.outcome == "ok"


def test_ia_con_cifras_inventadas_nunca_llega_a_mostrarse(
    caso, user, django_capture_on_commit_callbacks
):
    user.set_ai_consent(True)
    invented = {"resumen": "Te sobran RD$9,999.00 al mes.", "estado": "viable"}
    FakeProvider.queue(invented, invented)
    plan = generar(caso, user, django_capture_on_commit_callbacks)
    assert plan.narrative_source == "reglas"
    assert "9,999" not in json.dumps(plan.ai_narrative)
    assert_cifras_del_motor(plan)
    assert AIInteraction.objects.get().outcome == "fallback"


@pytest.mark.parametrize("salary", ["50000", "40000", "43000", "30000"])
def test_ninguna_cifra_de_la_narrativa_difiere_del_motor(
    personal_ws, user, salary, django_capture_on_commit_callbacks
):
    user.set_ai_consent(True)
    load_caso_50000(personal_ws, salary=salary)
    plan = generar(personal_ws, user, django_capture_on_commit_callbacks)
    assert plan.narrative_source == "ia"
    assert plan.ai_narrative["estado"] == plan.plan_status
    assert_cifras_del_motor(plan)


def test_caso_no_viable_tiene_faltante_fecha_y_alternativas(
    personal_ws, user, django_capture_on_commit_callbacks
):
    load_caso_50000(personal_ws, salary="40000")
    plan = generar(personal_ws, user, django_capture_on_commit_callbacks)
    assert plan.plan_status == "no_viable"
    assert plan.computed["faltante_total"] == "2000.00"
    assert plan.computed["faltantes_por_fecha"][0]["fecha"] == "2026-10-27"
    viables = [a for a in plan.computed["alternativas"] if a["estado_resultante"] != "no_viable"]
    assert len(viables) >= 2
    assert "27 de octubre" in plan.ai_narrative["resumen"]


def test_falla_inesperada_igual_entrega_el_plan(caso, user, django_capture_on_commit_callbacks):
    with mock.patch.object(generate, "run_structured", side_effect=RuntimeError("boom")):
        plan = generar(caso, user, django_capture_on_commit_callbacks)
    assert plan.status == PlanVersion.Status.PROPUESTA
    assert plan.narrative_source == "reglas"


def test_narrar_dos_veces_no_hace_nada(caso, user, django_capture_on_commit_callbacks):
    plan = generar(caso, user, django_capture_on_commit_callbacks)
    before = plan.ai_narrative
    assert narrate_plan(plan.pk).ai_narrative == before


def test_datos_faltantes(personal_ws, user, django_capture_on_commit_callbacks):
    plan = generar(personal_ws, user, django_capture_on_commit_callbacks)
    campos = [m["campo"] for m in plan.missing_data]
    assert campos[:2] == ["ingresos", "esenciales"]  # primero los de prioridad alta
    assert {"compromisos", "cuentas", "ahorro", "preferencias"} <= set(campos)
    assert plan.plan_status == "no_viable"
    assert plan.ai_narrative["advertencias_datos_faltantes"][0] == "No registraste ingresos."


def test_datos_faltantes_ingreso_variable(caso):
    IncomeSource.objects.for_workspace(caso).update(frequency="variable", pay_days=[])
    from apps.personal.services.loaders import load_personal_inputs

    inputs = load_personal_inputs(caso, HOY)
    missing = compute_missing_data(inputs, has_balances=True)
    assert [m["campo"] for m in missing] == ["ingresos"]
    assert "variable" in missing[0]["mensaje"]
