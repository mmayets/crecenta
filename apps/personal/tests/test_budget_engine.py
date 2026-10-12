from dataclasses import replace
from datetime import date
from decimal import Decimal

from apps.core.periods import Frequency, IncomeInput
from apps.personal.services.budget_engine import build_personal_plan, compute_plan
from apps.personal.services.types import (
    CommitmentInput,
    DebtInput,
    EssentialInput,
    LineKind,
    PlanStatus,
    Priority,
    SavingsFrequency,
    SavingsTiming,
)

from .builders import COMPROMISOS, OCTUBRE, QUINCENAS, D, ahorro, caso_50000, mensual, quincenal


class TestCaso50000:
    def test_coincide_exactamente(self):
        r = build_personal_plan(caso_50000())
        assert r.status == PlanStatus.VIABLE and r.viable
        assert r.income_total == D("50000")
        assert r.totals_by_kind == {
            "compromiso": D("20000.00"),
            "deuda": D("0"),
            "esencial": D("15000.00"),
            "ahorro": D("7000.00"),
            "discrecional": D("5000.00"),
            "reserva": D("3000.00"),
        }
        assert r.total_assigned == D("50000.00")
        assert r.deficit == 0
        assert r.shortfalls == ()
        assert r.alternatives == ()
        assert r.reserve_minimum == D("1500.00")

    def test_reparto_en_un_cobro(self):
        (cobro,) = build_personal_plan(caso_50000()).by_pay_event
        assert cobro.date == date(2026, 10, 1)
        assert (cobro.commitments, cobro.savings, cobro.essentials) == (
            D("20000"),
            D("7000.00"),
            D("15000.00"),
        )
        assert (cobro.discretionary, cobro.reserve, cobro.left) == (D("5000.00"), D("3000.00"), 0)

    def test_linea_de_tiempo(self):
        r = build_personal_plan(caso_50000())
        assert len(r.timeline) == 31
        assert r.timeline[0].inflows == D("50000")
        # Al cierre del período queda exactamente la reserva.
        assert r.timeline[-1].balance == D("3000.00")
        assert sum(p.variable_spend for p in r.timeline) == D("20000.00")
        assert min(p.balance for p in r.timeline) == D("3000.00")

    def test_vencimientos_fechados(self):
        r = build_personal_plan(caso_50000())
        alquiler = r.line("alquiler")
        assert alquiler.due_dates == (date(2026, 10, 5),)
        assert alquiler.kind == LineKind.COMPROMISO
        assert r.line("no-existe") is None
        assert {(i.ref, i.date, i.pay_event_date) for i in r.scheduled} >= {
            ("alquiler", date(2026, 10, 5), date(2026, 10, 1)),
            ("fondo", date(2026, 10, 1), date(2026, 10, 1)),
        }

    def test_supuestos(self):
        r = build_personal_plan(caso_50000())
        assert any("10.00%" in a and "RD$1,500.00" in a for a in r.assumptions)
        assert any("no con dinero guardado" in a for a in r.assumptions)
        assert not r.income_is_estimate


class TestQuincenal:
    def test_ahorro_3500_por_quincena(self):
        r = build_personal_plan(
            caso_50000(
                period=QUINCENAS,
                incomes=(quincenal(),),
                savings=(ahorro("3500", SavingsFrequency.QUINCENAL),),
            )
        )
        assert r.status == PlanStatus.VIABLE
        assert r.totals_by_kind["ahorro"] == D("7000.00")
        assert r.total_assigned == D("50000.00")
        assert [e.savings for e in r.by_pay_event] == [D("3500.00"), D("3500.00")]
        assert [e.date for e in r.by_pay_event] == [date(2026, 10, 15), date(2026, 10, 30)]

    def test_ahorro_mensual_se_reparte_entre_quincenas(self):
        r = build_personal_plan(caso_50000(period=QUINCENAS, incomes=(quincenal(),)))
        assert [e.savings for e in r.by_pay_event] == [D("3500.00"), D("3500.00")]

    def test_cada_cobro_cubre_sus_vencimientos_sin_sobrante_negativo(self):
        r = build_personal_plan(caso_50000(period=QUINCENAS, incomes=(quincenal(),)))
        first, second = r.by_pay_event
        # Luz (15) e internet (20) con el cobro del 15; alquiler (5 nov) con el del 30.
        assert (first.commitments, second.commitments) == (D("5000"), D("15000"))
        assert first.left == second.left == 0
        assert sum(e.assigned for e in r.by_pay_event) == D("50000.00")


class TestNoViable:
    def test_faltante_total_fecha_y_alternativas(self):
        r = build_personal_plan(caso_50000(incomes=(mensual("40000"),)))
        assert r.status == PlanStatus.NO_VIABLE and not r.viable
        assert r.deficit == D("2000.00")
        assert r.totals_by_kind["discrecional"] == 0 and r.totals_by_kind["reserva"] == 0
        # El gasto variable agota el dinero el 27 de octubre.
        (falta,) = r.shortfalls
        assert falta.date == date(2026, 10, 27)
        assert falta.amount == D("64.52")
        assert falta.labels == ("Gastos del día a día",)
        assert r.timeline[-1].balance == D("-2000.00")

        viables = [a for a in r.alternatives if a.status != PlanStatus.NO_VIABLE]
        assert len(viables) >= 2
        bajar = next(a for a in r.alternatives if a.code == "bajar_ahorro")
        assert bajar.freed == D("2000.00")
        assert bajar.deficit == 0
        assert [(c.target, c.before, c.after) for c in bajar.changes] == [
            ("fondo", D("7000.00"), D("5000.00"))
        ]

    def test_alternativas_recalculadas_por_el_motor(self):
        inputs = caso_50000(incomes=(mensual("40000"),))
        r = build_personal_plan(inputs)
        for alt in r.alternatives:
            assert alt.status in PlanStatus
        bajar = next(a for a in r.alternatives if a.code == "bajar_ahorro")
        manual = compute_plan(replace(inputs, savings=(ahorro("5000"),)))
        assert (manual.status, manual.deficit) == (bajar.status, bajar.deficit)

    def test_faltante_por_fecha_aunque_el_total_alcance(self):
        inputs = caso_50000(
            period=QUINCENAS,
            incomes=(quincenal(),),
            commitments=(CommitmentInput("alquiler", "Alquiler", D("21000"), due_day=20),),
            essentials=(EssentialInput("comida", "Comida", D("4000"), "c-comida"),),
            discretionary_wish=D("2000"),
        )
        r = build_personal_plan(inputs)
        assert r.deficit == 0
        assert r.status == PlanStatus.NO_VIABLE
        falta = r.shortfalls[0]
        assert falta.date == date(2026, 10, 20)
        assert falta.refs == ("alquiler",)
        assert falta.amount == D("661.29")
        codes = [a.code for a in r.alternatives]
        assert codes[0] == "repartir_entre_cobros"
        assert r.alternatives[0].status == PlanStatus.VIABLE
        assert "bajar_ahorro" in codes

    def test_alternativa_combinada(self):
        r = build_personal_plan(
            caso_50000(
                incomes=(mensual("28000"),),
                essentials=(EssentialInput("comida", "Comida", D("10000"), "c-comida"),),
                savings=(ahorro("3000"),),
                discretionary_wish=D("2000"),
                preferences={"c-comida": Priority.REDUCIBLE},
            )
        )
        assert r.deficit == D("5000.00")
        assert all(a.status == PlanStatus.NO_VIABLE for a in r.alternatives)
        combinada = next(a for a in r.alternatives if a.code == "combinada")
        assert combinada.deficit == D("500.00")
        assert {c.target for c in combinada.changes} == {"comida", "fondo"}

    def test_sin_cobros(self):
        r = build_personal_plan(caso_50000(incomes=()))
        assert r.status == PlanStatus.NO_VIABLE
        assert r.deficit == D("42000.00")
        assert r.by_pay_event == ()
        assert any("No hay cobros" in a for a in r.assumptions)
        assert {i.pay_event_date for i in r.scheduled} == {None}


class TestAjustado:
    def test_ocio_deseado_no_alcanza(self):
        r = build_personal_plan(caso_50000(discretionary_wish=D("7500")))
        assert r.status == PlanStatus.AJUSTADO and r.viable
        assert r.totals_by_kind["discrecional"] == D("6500.00")
        assert r.totals_by_kind["reserva"] == D("1500.00")
        usar = next(a for a in r.alternatives if a.code == "usar_reserva")
        assert usar.status == PlanStatus.VIABLE
        assert {c.target: c.after for c in usar.changes} == {
            "discrecional": D("7500.00"),
            "reserva": D("500.00"),
        }

    def test_reserva_bajo_el_minimo(self):
        r = build_personal_plan(caso_50000(incomes=(mensual("43000"),), discretionary_wish=None))
        assert r.status == PlanStatus.AJUSTADO
        assert r.totals_by_kind["reserva"] == D("1000.00")
        assert r.totals_by_kind["discrecional"] == 0

    def test_sin_ocio_deseado_reserva_minima_y_resto_a_ocio(self):
        r = build_personal_plan(caso_50000(discretionary_wish=None))
        assert r.status == PlanStatus.VIABLE
        assert r.totals_by_kind["reserva"] == D("1500.00")
        assert r.totals_by_kind["discrecional"] == D("6500.00")


class TestDeudasYCompromisos:
    def test_cuota_de_deuda(self):
        deuda = DebtInput("prestamo", "Préstamo", D("4000"), D("20000"), due_day=10)
        r = build_personal_plan(caso_50000(debts=(deuda,), discretionary_wish=D("1000")))
        assert r.line("prestamo").amount == D("4000.00")
        assert r.line("prestamo").due_dates == (date(2026, 10, 10),)
        assert r.totals_by_kind["deuda"] == D("4000.00")

    def test_ultima_cuota_es_el_saldo(self):
        deuda = DebtInput("prestamo", "Préstamo", D("4000"), D("1500"), due_day=10)
        r = compute_plan(caso_50000(debts=(deuda,)))
        assert r.line("prestamo").amount == D("1500.00")

    def test_deuda_saldada_o_vencida_se_omite(self):
        saldada = DebtInput("a", "A", D("4000"), D("0"), due_day=10)
        vencida = DebtInput("b", "B", D("4000"), D("9000"), due_day=10, end_date=date(2026, 9, 1))
        fin = DebtInput("c", "C", D("4000"), D("9000"), due_day=20, end_date=date(2026, 10, 15))
        r = compute_plan(caso_50000(debts=(saldada, vencida, fin)))
        assert r.totals_by_kind["deuda"] == 0

    def test_compromiso_quincenal_y_semanal(self):
        colegio = CommitmentInput("colegio", "Colegio", D("1000"), Frequency.QUINCENAL, due_day=20)
        assert colegio.due_days() == (5, 20)
        assert CommitmentInput("x", "X", D("1"), Frequency.QUINCENAL, 10).due_days() == (10, 25)
        guagua = CommitmentInput("guagua", "Pasaje", D("500"), Frequency.SEMANAL, due_day=0)
        cero = CommitmentInput("cero", "Cero", D("0"))
        r = compute_plan(caso_50000(commitments=(colegio, guagua, cero)))
        assert r.line("colegio").amount == D("2000.00")
        assert r.line("guagua").amount == D("2000.00")  # 4 lunes en octubre 2026
        assert r.line("cero") is None


class TestIngresosYAhorro:
    def test_ingreso_variable_es_estimado(self):
        variable = IncomeInput("extra", D("50000"), Frequency.VARIABLE)
        r = compute_plan(caso_50000(incomes=(variable,)))
        assert r.income_is_estimate
        assert any("variable" in a for a in r.assumptions)

    def test_promedio_de_historial(self):
        esencial = EssentialInput("comida", "Comida", D("15000"), "c", from_history=True)
        r = compute_plan(caso_50000(essentials=(esencial,)))
        assert any("Comida: promedio" in a for a in r.assumptions)

    def test_ahorro_en_el_ultimo_cobro(self):
        r = compute_plan(
            caso_50000(
                period=QUINCENAS, incomes=(quincenal(),), savings_timing=SavingsTiming.ULTIMO_COBRO
            )
        )
        assert [e.savings for e in r.by_pay_event] == [0, D("7000.00")]

    def test_meta_alcanzada_no_aporta(self):
        r = compute_plan(
            caso_50000(savings=(ahorro(target_amount=D("1000"), saved_so_far=D("1000")),))
        )
        assert r.line("fondo") is None

    def test_esencial_en_cero_se_omite(self):
        r = compute_plan(caso_50000(essentials=(EssentialInput("x", "X", D("0")),)))
        assert r.line("x") is None

    def test_viable_no_genera_alternativas_aunque_se_pida(self):
        assert build_personal_plan(caso_50000(), with_alternatives=True).alternatives == ()
        no_viable = caso_50000(incomes=(mensual("40000"),))
        assert build_personal_plan(no_viable, with_alternatives=False).alternatives == ()


def test_compromisos_por_defecto():
    assert sum(c.amount for c in COMPROMISOS) == D("20000")
    assert OCTUBRE.days == 31
    assert Decimal("0") == 0


def test_sin_ingresos_ni_gastos_no_es_viable():
    from apps.personal.services.types import PersonalInputs

    r = build_personal_plan(PersonalInputs(period=OCTUBRE, incomes=()))
    assert r.status == PlanStatus.NO_VIABLE
    assert r.deficit == 0 and r.alternatives == ()
