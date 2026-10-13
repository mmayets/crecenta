"""Tipos de entrada y salida del motor del plan personal.

Son dataclasses inmutables sin dependencias del ORM: el motor es una función pura y determinística.
Las referencias (`ref`, `category_ref`) son cadenas (UUID en texto) para poder serializar el
resultado y anonimizarlo antes de enviarlo a la IA.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum

from apps.core.periods import Frequency, IncomeInput, Period


class Priority(StrEnum):
    PRIORITARIO = "prioritario"
    REDUCIBLE = "reducible"


class SavingsFrequency(StrEnum):
    DIARIA = "diaria"
    SEMANAL = "semanal"
    QUINCENAL = "quincenal"
    MENSUAL = "mensual"


class DailyMode(StrEnum):
    TODOS_LOS_DIAS = "todos_los_dias"
    DIAS_SELECCIONADOS = "dias_seleccionados"


class SavingsTiming(StrEnum):
    PROPORCIONAL = "proporcional"  # el aporte se reparte entre los cobros según su monto
    ULTIMO_COBRO = "ultimo_cobro"  # todo el aporte se separa en el último cobro del período


class LineKind(StrEnum):
    COMPROMISO = "compromiso"
    DEUDA = "deuda"
    ESENCIAL = "esencial"
    AHORRO = "ahorro"
    DISCRECIONAL = "discrecional"
    RESERVA = "reserva"


class PlanStatus(StrEnum):
    VIABLE = "viable"
    AJUSTADO = "ajustado"
    NO_VIABLE = "no_viable"


# ---------------------------------------------------------------- entradas


@dataclass(frozen=True)
class CommitmentInput:
    """Compromiso fijo (alquiler, luz, colegio…). `amount` es el monto de cada vencimiento."""

    ref: str
    name: str
    amount: Decimal
    frequency: Frequency = Frequency.MENSUAL
    due_day: int = 1  # día del mes (mensual/quincenal) o de la semana (semanal)
    category_ref: str | None = None
    is_fixed: bool = True
    due_month: int | None = None  # solo anual

    def due_days(self) -> tuple[int, ...]:
        if self.frequency == Frequency.QUINCENAL:
            second = self.due_day + 15 if self.due_day <= 15 else self.due_day - 15
            return tuple(sorted({self.due_day, second}))
        return (self.due_day,)


@dataclass(frozen=True)
class DebtInput:
    """Deuda con cuota mensual. Se omite si está saldada o si su fecha final ya pasó."""

    ref: str
    name: str
    installment: Decimal
    balance: Decimal
    due_day: int
    end_date: date | None = None
    interest_rate: Decimal | None = None
    category_ref: str | None = None


@dataclass(frozen=True)
class EssentialInput:
    """Esencial variable (alimentación, transporte…). `amount` es el presupuesto del período."""

    ref: str
    name: str
    amount: Decimal
    category_ref: str | None = None
    from_history: bool = False


@dataclass(frozen=True)
class SavingsInput:
    ref: str
    purpose: str
    contribution_amount: Decimal
    frequency: SavingsFrequency = SavingsFrequency.MENSUAL
    daily_mode: DailyMode = DailyMode.TODOS_LOS_DIAS
    selected_weekdays: frozenset[int] = frozenset()
    target_amount: Decimal | None = None
    saved_so_far: Decimal = Decimal("0")
    deadline: date | None = None
    category_ref: str | None = None


@dataclass(frozen=True)
class PersonalInputs:
    period: Period
    incomes: tuple[IncomeInput, ...]
    commitments: tuple[CommitmentInput, ...] = ()
    debts: tuple[DebtInput, ...] = ()
    essentials: tuple[EssentialInput, ...] = ()
    savings: tuple[SavingsInput, ...] = ()
    discretionary_wish: Decimal | None = None  # monto de ocio deseado; None = lo que sobre
    reserve_pct: Decimal = Decimal("0.10")  # reserva mínima sobre esenciales variables
    preferences: dict[str, Priority] = field(default_factory=dict)  # category_ref → prioridad
    opening_cash: Decimal = Decimal("0")  # efectivo al inicio del período (línea de tiempo)
    savings_timing: SavingsTiming = SavingsTiming.PROPORCIONAL


# ---------------------------------------------------------------- salidas


@dataclass(frozen=True)
class PlanLine:
    ref: str
    kind: LineKind
    name: str
    amount: Decimal
    category_ref: str | None = None
    due_dates: tuple[date, ...] = ()


@dataclass(frozen=True)
class ScheduledItem:
    """Salida fechada del plan (vencimiento o aporte) y el cobro que la cubre."""

    date: date
    amount: Decimal
    ref: str
    kind: LineKind
    category_ref: str | None
    pay_event_date: datetime.date | None


@dataclass(frozen=True)
class PayEventAllocation:
    """Reparto de un cobro: cuánto se separa para cada cosa al recibirlo."""

    date: date
    income: Decimal
    commitments: Decimal
    savings: Decimal
    essentials: Decimal
    discretionary: Decimal
    reserve: Decimal

    @property
    def assigned(self) -> Decimal:
        return self.commitments + self.savings + self.essentials + self.discretionary + self.reserve

    @property
    def left(self) -> Decimal:
        return self.income - self.assigned


@dataclass(frozen=True)
class TimelinePoint:
    date: date
    inflows: Decimal  # cobrado ese día
    outflows: Decimal  # vencimientos y ahorro de ese día
    variable_spend: Decimal  # gasto variable (esenciales + ocio) estimado de ese día
    balance: Decimal  # saldo estimado al cierre del día


@dataclass(frozen=True)
class Shortfall:
    """Día en que el dinero cobrado hasta esa fecha no alcanza."""

    date: date
    amount: Decimal  # faltante al cierre del día
    refs: tuple[str, ...]  # compromisos/deudas que vencen ese día (vacío = gasto variable)
    labels: tuple[str, ...]


@dataclass(frozen=True)
class Change:
    target: str  # ref de la línea o categoría afectada
    label: str
    before: Decimal
    after: Decimal


@dataclass(frozen=True)
class Alternative:
    code: str
    name: str
    description: str
    changes: tuple[Change, ...]
    freed: Decimal  # dinero liberado en el período
    status: PlanStatus  # estado del plan si se aplica (recalculado por el motor)
    deficit: Decimal  # faltante total que queda si se aplica
    max_shortfall: Decimal  # mayor faltante por fechas que queda si se aplica
    touches_priority: bool = False  # modifica algo que el usuario marcó como prioritario


@dataclass(frozen=True)
class BudgetResult:
    period: Period
    income_total: Decimal
    lines: tuple[PlanLine, ...]
    totals_by_kind: dict[str, Decimal]
    reserve_minimum: Decimal
    deficit: Decimal  # cuánto falta para cubrir compromisos, deudas, esenciales y ahorro
    status: PlanStatus
    shortfalls: tuple[Shortfall, ...]
    timeline: tuple[TimelinePoint, ...]
    by_pay_event: tuple[PayEventAllocation, ...]
    scheduled: tuple[ScheduledItem, ...]
    alternatives: tuple[Alternative, ...]
    assumptions: tuple[str, ...]
    income_is_estimate: bool

    @property
    def viable(self) -> bool:
        return self.status != PlanStatus.NO_VIABLE

    @property
    def total_assigned(self) -> Decimal:
        return sum((line.amount for line in self.lines), Decimal("0"))

    @property
    def max_shortfall(self) -> Decimal:
        return max((s.amount for s in self.shortfalls), default=Decimal("0"))

    def line(self, ref: str) -> PlanLine | None:
        return next((line for line in self.lines if line.ref == ref), None)

    def total(self, *kinds: LineKind) -> Decimal:
        return sum((self.totals_by_kind.get(k, Decimal("0")) for k in kinds), Decimal("0"))
