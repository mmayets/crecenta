"""Utilidades de fechas para períodos y vencimientos."""

from __future__ import annotations

import calendar
from collections.abc import Iterator
from datetime import date, timedelta


def days_in_month(year: int, month: int) -> int:
    """Días reales del mes (considera años bisiestos)."""
    return calendar.monthrange(year, month)[1]


def clamp_day(year: int, month: int, day: int) -> date:
    """Fecha con `day` ajustado al último día del mes si no existe (31 en abril → 30)."""
    if day < 1:
        raise ValueError("El día debe ser mayor o igual a 1")
    return date(year, month, min(day, days_in_month(year, month)))


def add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    """Suma `delta` meses a (año, mes)."""
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def iter_days(start: date, end: date) -> Iterator[date]:
    """Itera los días del rango cerrado [start, end]."""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def count_days(start: date, end: date) -> int:
    """Número de días del rango cerrado [start, end] (0 si end < start)."""
    return max((end - start).days + 1, 0)


def count_weekdays(start: date, end: date, weekdays: set[int]) -> int:
    """Cuenta los días del rango cerrado cuyo `weekday()` (lunes=0) está en `weekdays`."""
    if end < start or not weekdays:
        return 0
    total_days = count_days(start, end)
    full_weeks, remainder = divmod(total_days, 7)
    count = full_weeks * len(weekdays)
    for offset in range(remainder):
        if (start + timedelta(days=full_weeks * 7 + offset)).weekday() in weekdays:
            count += 1
    return count


def monthly_dates(start: date, end: date, day: int) -> list[date]:
    """Fechas con día `day` (ajustado a fin de mes) dentro del rango cerrado [start, end]."""
    result: list[date] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        candidate = clamp_day(year, month, day)
        if start <= candidate <= end:
            result.append(candidate)
        year, month = add_months(year, month, 1)
    return result


def weekly_dates(start: date, end: date, weekday: int) -> list[date]:
    """Fechas del rango cerrado que caen en `weekday` (lunes=0)."""
    if not 0 <= weekday <= 6:
        raise ValueError("weekday debe estar entre 0 (lunes) y 6 (domingo)")
    first = start + timedelta(days=(weekday - start.weekday()) % 7)
    result: list[date] = []
    current = first
    while current <= end:
        result.append(current)
        current += timedelta(days=7)
    return result
