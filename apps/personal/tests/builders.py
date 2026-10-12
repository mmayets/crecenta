"""Entradas de prueba del motor (sin base de datos)."""

from datetime import date
from decimal import Decimal

from apps.core.periods import Frequency, IncomeInput, Period
from apps.personal.services.types import (
    CommitmentInput,
    EssentialInput,
    PersonalInputs,
    Priority,
    SavingsFrequency,
    SavingsInput,
)

D = Decimal
OCTUBRE = Period(date(2026, 10, 1), date(2026, 10, 31))
QUINCENAS = Period(date(2026, 10, 15), date(2026, 11, 14))


def mensual(amount="50000", day=1):
    return IncomeInput("salario", D(amount), Frequency.MENSUAL, (day,))


def quincenal(amount="25000", days=(15, 30)):
    return IncomeInput("salario", D(amount), Frequency.QUINCENAL, days)


COMPROMISOS = (
    CommitmentInput("alquiler", "Alquiler", D("15000"), due_day=5, category_ref="c-alquiler"),
    CommitmentInput("luz", "Electricidad", D("2500"), due_day=15, category_ref="c-luz"),
    CommitmentInput("internet", "Internet", D("2500"), due_day=20, category_ref="c-internet"),
)
ESENCIALES = (
    EssentialInput("alimentacion", "Alimentación", D("10000"), "c-alimentacion"),
    EssentialInput("transporte", "Transporte", D("5000"), "c-transporte"),
)


def ahorro(amount="7000", frequency=SavingsFrequency.MENSUAL, **kw):
    return SavingsInput(
        "fondo", "Fondo de emergencia", D(amount), frequency, category_ref="c-ahorro", **kw
    )


def caso_50000(**overrides):
    """Encargo §7: salario neto RD$50,000 → compromisos 20,000; esenciales 15,000; ahorro 7,000;
    ocio 5,000; reserva 3,000."""
    data = {
        "period": OCTUBRE,
        "incomes": (mensual(),),
        "commitments": COMPROMISOS,
        "essentials": ESENCIALES,
        "savings": (ahorro(),),
        "discretionary_wish": D("5000"),
        "preferences": {"c-alimentacion": Priority.REDUCIBLE},
    }
    data.update(overrides)
    return PersonalInputs(**data)
