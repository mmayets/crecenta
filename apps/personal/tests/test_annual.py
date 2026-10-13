from datetime import date

from apps.core.periods import Frequency
from apps.personal.services.budget_engine import build_personal_plan
from apps.personal.services.serialize import inputs_from_dict, inputs_to_dict
from apps.personal.services.types import CommitmentInput, LineKind

from .builders import COMPROMISOS, D, caso_50000

MARBETE = CommitmentInput(
    ref="c-marbete", name="Marbete", amount=D("3600"), frequency=Frequency.ANUAL, due_day=15,
    due_month=3, category_ref="c-seguros",
)  # fmt: skip


def test_pago_anual_se_cubre_con_provision_mensual():
    r = build_personal_plan(caso_50000(commitments=(*COMPROMISOS, MARBETE)))
    line = next(line for line in r.lines if line.ref == "c-marbete")
    assert line.kind == LineKind.COMPROMISO and line.name == "Apartar para Marbete"
    assert line.amount == D("300.00") and line.due_dates == (date(2026, 10, 1),)
    assert r.totals_by_kind["compromiso"] == D("20300.00")
    assert any("pago anual de RD$3,600.00 en marzo" in a for a in r.assumptions)
    # El caso del encargo sigue cuadrando: los 300 salen de lo libre (ocio/reserva).
    assert r.total_assigned == D("50000.00") and r.status.value in {"viable", "ajustado"}


def test_pago_anual_en_cero_se_ignora_y_sin_cobros_usa_inicio():
    gratis = CommitmentInput(ref="x", name="X", amount=D("0"), frequency=Frequency.ANUAL)
    r = build_personal_plan(caso_50000(commitments=(gratis,)))
    assert all(line.ref != "x" for line in r.lines)
    sin_cobros = build_personal_plan(caso_50000(incomes=(), commitments=(MARBETE,)))
    line = next(line for line in sin_cobros.lines if line.ref == "c-marbete")
    assert line.due_dates == (sin_cobros.period.start,)


def test_serializacion_conserva_el_mes():
    inputs = caso_50000(commitments=(MARBETE,))
    data = inputs_to_dict(inputs)
    assert data["compromisos"][0]["mes"] == 3
    assert inputs_from_dict(data).commitments[0].due_month == 3
    del data["compromisos"][0]["mes"]  # planes guardados antes de la Fase 3
    assert inputs_from_dict(data).commitments[0].due_month is None
