from datetime import date

import pytest

from apps.core.dates import (
    add_months,
    clamp_day,
    count_days,
    count_weekdays,
    days_in_month,
    iter_days,
    monthly_dates,
    weekly_dates,
)


def test_dias_del_mes_bisiesto():
    assert days_in_month(2024, 2) == 29
    assert days_in_month(2025, 2) == 28
    assert days_in_month(2026, 10) == 31


def test_clamp_day():
    assert clamp_day(2026, 4, 31) == date(2026, 4, 30)
    assert clamp_day(2026, 2, 30) == date(2026, 2, 28)
    assert clamp_day(2026, 1, 15) == date(2026, 1, 15)
    with pytest.raises(ValueError):
        clamp_day(2026, 1, 0)


@pytest.mark.parametrize(
    ("ym", "delta", "expected"),
    [((2026, 12), 1, (2027, 1)), ((2026, 1), -1, (2025, 12)), ((2026, 5), 14, (2027, 7))],
)
def test_add_months(ym, delta, expected):
    assert add_months(*ym, delta) == expected


def test_iter_y_count_days():
    days = list(iter_days(date(2026, 2, 27), date(2026, 3, 2)))
    assert len(days) == 4 == count_days(date(2026, 2, 27), date(2026, 3, 2))
    assert count_days(date(2026, 3, 2), date(2026, 3, 1)) == 0


def test_count_weekdays():
    # Octubre 2026: 1 de octubre es jueves. Lunes a viernes = 22 días hábiles.
    assert count_weekdays(date(2026, 10, 1), date(2026, 10, 31), {0, 1, 2, 3, 4}) == 22
    # Sábados y domingos.
    assert count_weekdays(date(2026, 10, 1), date(2026, 10, 31), {5, 6}) == 9
    assert count_weekdays(date(2026, 10, 2), date(2026, 10, 1), {0}) == 0
    assert count_weekdays(date(2026, 10, 1), date(2026, 10, 31), set()) == 0


def test_monthly_dates_ajusta_fin_de_mes():
    assert monthly_dates(date(2026, 1, 15), date(2026, 4, 14), 31) == [
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 31),
    ]


def test_weekly_dates():
    # 2026-10-02 es viernes (4).
    assert weekly_dates(date(2026, 10, 1), date(2026, 10, 20), 4) == [
        date(2026, 10, 2),
        date(2026, 10, 9),
        date(2026, 10, 16),
    ]
    with pytest.raises(ValueError):
        weekly_dates(date(2026, 10, 1), date(2026, 10, 20), 7)
