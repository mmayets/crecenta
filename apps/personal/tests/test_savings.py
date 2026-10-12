from datetime import date

import pytest

from apps.core.periods import Frequency, IncomeInput, PayEvent, Period
from apps.personal.services.savings import (
    contributions_in_period,
    goal_progress,
    occurrences_in_period,
    remaining_to_target,
    split_across_pay_events,
)
from apps.personal.services.types import DailyMode, SavingsFrequency, SavingsTiming

from .builders import OCTUBRE, D, ahorro

FEBRERO = Period(date(2026, 2, 1), date(2026, 2, 28))


@pytest.mark.parametrize(
    ("goal", "period", "expected"),
    [
        (ahorro("100", SavingsFrequency.DIARIA), OCTUBRE, 31),
        (ahorro("100", SavingsFrequency.DIARIA), FEBRERO, 28),
        (ahorro("100", SavingsFrequency.DIARIA), Period(date(2024, 2, 1), date(2024, 2, 29)), 29),
        # Lunes a viernes de octubre 2026: 22 días.
        (
            ahorro(
                "100",
                SavingsFrequency.DIARIA,
                daily_mode=DailyMode.DIAS_SELECCIONADOS,
                selected_weekdays=frozenset({0, 1, 2, 3, 4}),
            ),
            OCTUBRE,
            22,
        ),
        (ahorro("100", SavingsFrequency.SEMANAL), OCTUBRE, 5),  # jueves 1, 8, 15, 22, 29
        (ahorro("100", SavingsFrequency.SEMANAL), FEBRERO, 4),
        (ahorro("100", SavingsFrequency.QUINCENAL), OCTUBRE, 2),
        (ahorro("100", SavingsFrequency.MENSUAL), OCTUBRE, 1),
    ],
)
def test_ocurrencias_con_dias_reales(goal, period, expected):
    assert occurrences_in_period(goal, period) == expected


def test_meta_diaria_usa_dias_reales_del_mes():
    goal = ahorro("50", SavingsFrequency.DIARIA)
    assert contributions_in_period(goal, OCTUBRE) == D("1550.00")
    assert contributions_in_period(goal, FEBRERO) == D("1400.00")


def test_no_aporta_mas_de_lo_que_falta():
    goal = ahorro("7000", target_amount=D("20000"), saved_so_far=D("16000"))
    assert remaining_to_target(goal) == D("4000")
    assert contributions_in_period(goal, OCTUBRE) == D("4000")
    assert remaining_to_target(ahorro()) is None


def test_reparto_entre_cobros():
    events = [
        PayEvent(date(2026, 10, 15), D("30000"), "a"),
        PayEvent(date(2026, 10, 30), D("20000"), "a"),
    ]
    assert split_across_pay_events(D("7000"), events) == [D("4200.00"), D("2800.00")]
    assert split_across_pay_events(D("7000"), events, SavingsTiming.ULTIMO_COBRO) == [
        D("0"),
        D("7000.00"),
    ]
    assert split_across_pay_events(D("7000"), []) == []


def test_avance_de_la_meta():
    goal = ahorro("3100", target_amount=D("31000"), saved_so_far=D("1000"))
    progress = goal_progress(
        goal, OCTUBRE, contributed_in_period=D("500"), today=date(2026, 10, 10)
    )
    assert progress.expected_to_date == D("1000.00")
    assert progress.shortfall == D("500.00")
    assert progress.at_risk
    assert progress.saved == D("1500")
    assert progress.pct_of_target == D("4.84")
    al_dia = goal_progress(goal, OCTUBRE, D("3100"), date(2026, 11, 5))
    assert not al_dia.at_risk
    antes = goal_progress(ahorro(), OCTUBRE, D("0"), date(2026, 9, 1))
    assert antes.expected_to_date == 0 and antes.pct_of_target is None


def test_ingreso_usado_en_builders():
    assert IncomeInput("x", D("1"), Frequency.MENSUAL, (1,)).monthly_equivalent() == D("1")
