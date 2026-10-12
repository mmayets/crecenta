from datetime import date
from decimal import Decimal

import pytest

from apps.core.periods import (
    Frequency,
    IncomeInput,
    Period,
    anchor_day,
    pay_events,
    period_for,
    total_income,
)

D = Decimal


def salario_mensual(day=1, amount="50000"):
    return IncomeInput(
        ref="salario", net_amount=D(amount), frequency=Frequency.MENSUAL, pay_days=(day,)
    )


def salario_quincenal(days=(15, 30), amount="25000"):
    return IncomeInput(
        ref="salario", net_amount=D(amount), frequency=Frequency.QUINCENAL, pay_days=days
    )


class TestValidacion:
    def test_quincenal_requiere_dos_dias(self):
        with pytest.raises(ValueError):
            IncomeInput(ref="x", net_amount=D("1"), frequency=Frequency.QUINCENAL, pay_days=(15,))

    def test_dia_fuera_de_rango(self):
        with pytest.raises(ValueError):
            IncomeInput(ref="x", net_amount=D("1"), frequency=Frequency.MENSUAL, pay_days=(32,))

    def test_semanal_dia_de_semana(self):
        with pytest.raises(ValueError):
            IncomeInput(ref="x", net_amount=D("1"), frequency=Frequency.SEMANAL, pay_days=(7,))

    def test_monto_negativo(self):
        with pytest.raises(ValueError):
            IncomeInput(ref="x", net_amount=D("-1"), frequency=Frequency.MENSUAL, pay_days=(1,))

    def test_periodo_invertido(self):
        with pytest.raises(ValueError):
            Period(date(2026, 2, 1), date(2026, 1, 1))


class TestEquivalenteMensual:
    def test_frecuencias(self):
        assert salario_mensual().monthly_equivalent() == D("50000")
        assert salario_quincenal().monthly_equivalent() == D("50000")
        semanal = IncomeInput(
            ref="s", net_amount=D("1200"), frequency=Frequency.SEMANAL, pay_days=(4,)
        )
        assert semanal.monthly_equivalent() == D("5200")
        variable = IncomeInput(ref="v", net_amount=D("8000"), frequency=Frequency.VARIABLE)
        assert variable.monthly_equivalent() == D("8000")
        assert variable.is_estimate
        variable2 = IncomeInput(
            ref="v", net_amount=D("8000"), frequency=Frequency.VARIABLE, pay_days=(10, 20)
        )
        assert variable2.monthly_equivalent() == D("16000")


class TestPeriodo:
    def test_mensual_dia_1_es_mes_calendario(self):
        p = period_for([salario_mensual(1)], date(2026, 10, 12))
        assert p == Period(date(2026, 10, 1), date(2026, 10, 31))
        assert p.days == 31

    def test_ancla_dia_25(self):
        p = period_for([salario_mensual(25)], date(2026, 10, 12))
        assert p == Period(date(2026, 9, 25), date(2026, 10, 24))

    def test_ancla_en_el_mismo_dia(self):
        p = period_for([salario_mensual(25)], date(2026, 10, 25))
        assert p.start == date(2026, 10, 25)

    def test_ancla_31_en_febrero(self):
        p = period_for([salario_mensual(31)], date(2026, 3, 5))
        assert p == Period(date(2026, 2, 28), date(2026, 3, 30))

    def test_quincenal_ancla_primer_dia(self):
        p = period_for([salario_quincenal((15, 30))], date(2026, 10, 12))
        assert p == Period(date(2026, 9, 15), date(2026, 10, 14))

    def test_sin_ingresos_mes_calendario(self):
        assert anchor_day([]) == 1
        semanal = IncomeInput(
            ref="s", net_amount=D("1"), frequency=Frequency.SEMANAL, pay_days=(4,)
        )
        assert anchor_day([semanal]) == 1

    def test_ingreso_principal_es_el_mayor(self):
        principal = salario_mensual(25, "40000")
        extra = IncomeInput(
            ref="extra", net_amount=D("5000"), frequency=Frequency.MENSUAL, pay_days=(10,)
        )
        assert anchor_day([extra, principal]) == 25

    def test_dias_transcurridos(self):
        p = Period(date(2026, 10, 1), date(2026, 10, 31))
        assert p.days_elapsed(date(2026, 9, 30)) == 0
        assert p.days_elapsed(date(2026, 10, 12)) == 12
        assert p.days_elapsed(date(2026, 11, 5)) == 31
        assert p.contains(date(2026, 10, 31))
        assert not p.contains(date(2026, 11, 1))


class TestEventosDeCobro:
    def test_mensual(self):
        p = Period(date(2026, 10, 1), date(2026, 10, 31))
        events = pay_events([salario_mensual(1)], p)
        assert [(e.date, e.amount) for e in events] == [(date(2026, 10, 1), D("50000"))]
        assert total_income(events) == D("50000")

    def test_quincenal_en_febrero(self):
        p = Period(date(2026, 2, 1), date(2026, 2, 28))
        events = pay_events([salario_quincenal((15, 30))], p)
        assert [e.date for e in events] == [date(2026, 2, 15), date(2026, 2, 28)]
        assert total_income(events) == D("50000")

    def test_semanal(self):
        p = Period(date(2026, 10, 1), date(2026, 10, 31))
        semanal = IncomeInput(
            ref="s", net_amount=D("1000"), frequency=Frequency.SEMANAL, pay_days=(4,)
        )
        events = pay_events([semanal], p)
        assert len(events) == 5  # viernes 2, 9, 16, 23, 30
        assert total_income(events) == D("5000")

    def test_variable_sin_fecha_al_inicio(self):
        p = Period(date(2026, 10, 1), date(2026, 10, 31))
        variable = IncomeInput(ref="v", net_amount=D("8000"), frequency=Frequency.VARIABLE)
        (event,) = pay_events([variable], p)
        assert event.date == p.start
        assert event.is_estimate

    def test_ignora_montos_cero_y_ordena(self):
        p = Period(date(2026, 10, 1), date(2026, 10, 31))
        cero = IncomeInput(
            ref="cero", net_amount=D("0"), frequency=Frequency.MENSUAL, pay_days=(5,)
        )
        extra = IncomeInput(
            ref="extra", net_amount=D("3000"), frequency=Frequency.MENSUAL, pay_days=(20,)
        )
        events = pay_events([extra, cero, salario_mensual(1)], p)
        assert [e.source_ref for e in events] == ["salario", "extra"]

    def test_variable_con_dias(self):
        p = Period(date(2026, 10, 1), date(2026, 10, 31))
        variable = IncomeInput(
            ref="v", net_amount=D("4000"), frequency=Frequency.VARIABLE, pay_days=(10, 20)
        )
        assert [e.date.day for e in pay_events([variable], p)] == [10, 20]
