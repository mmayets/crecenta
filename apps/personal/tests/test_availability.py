from dataclasses import replace
from datetime import date

from apps.personal.services.availability import compute_availability
from apps.personal.services.budget_engine import build_personal_plan
from apps.personal.services.types import CommitmentInput

from .builders import QUINCENAS, D, caso_50000, quincenal


def test_disponible_para_gastar_excluye_lo_comprometido():
    plan = build_personal_plan(caso_50000())
    # 10 de octubre: cobró 50,000, pagó el alquiler (15,000) y gastó 2,000 en comida.
    a = compute_availability(
        plan,
        date(2026, 10, 10),
        in_accounts=D("33000"),
        spent_by_category={"c-alquiler": D("15000"), "c-alimentacion": D("2000")},
        savings_contributed=D("0"),
    )
    assert a.pending_commitments == D("5000")  # luz e internet aún sin pagar
    assert a.pending_savings == D("7000.00")
    assert a.reserves == D("3000.00")
    assert a.spendable == D("18000.00")
    assert a.committed == D("15000.00")
    assert a.next_pay_date is None
    assert not a.is_short


def test_pago_parcial_y_ahorro_aportado():
    plan = build_personal_plan(caso_50000())
    a = compute_availability(
        plan,
        date(2026, 10, 25),
        in_accounts=D("10000"),
        spent_by_category={"c-alquiler": D("15000"), "c-luz": D("1000"), "c-internet": D("2500")},
        savings_contributed=D("7000"),
    )
    assert a.pending_commitments == D("1500")
    assert a.pending_savings == 0
    assert a.spendable == D("5500.00")


def test_quincenal_solo_descuenta_lo_cubierto_por_cobros_recibidos():
    plan = build_personal_plan(caso_50000(period=QUINCENAS, incomes=(quincenal(),)))
    a = compute_availability(
        plan,
        date(2026, 10, 16),
        in_accounts=D("25000"),
        spent_by_category={},
        savings_contributed=D("0"),
    )
    # El alquiler (5 nov) se cubre con el cobro del 30: no compromete el dinero de hoy.
    assert a.pending_commitments == D("5000")
    assert a.pending_savings == D("3500.00")
    first, _ = plan.by_pay_event
    assert a.reserves == first.reserve
    assert a.next_pay_date == date(2026, 10, 30)


def test_negativo_se_muestra_como_faltante():
    plan = build_personal_plan(caso_50000())
    a = compute_availability(plan, date(2026, 10, 2), D("1000"), {}, D("0"))
    assert a.spendable < 0 and a.is_short


def test_compromiso_sin_categoria_pasado_se_da_por_pagado():
    sin_cat = CommitmentInput("cable", "Cable", D("1000"), due_day=3)
    proximo = CommitmentInput("gym", "Gimnasio", D("800"), due_day=20)
    plan = build_personal_plan(replace(caso_50000(), commitments=(sin_cat, proximo)))
    a = compute_availability(plan, date(2026, 10, 10), D("40000"), {}, D("0"))
    assert a.pending_commitments == D("800")
