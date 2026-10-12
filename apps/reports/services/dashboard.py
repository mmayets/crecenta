"""Inicio de un espacio personal: "¿Cómo voy este mes, cuánto me queda y qué debo ajustar?".

Todo sale de servicios ya probados (plan, disponibilidad, alertas); aquí solo se agrupa.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from apps.alerts.models import Alert
from apps.alerts.services.evaluate import build_context
from apps.alerts.services.rules_personal import DISCRETIONARY_REF
from apps.core.money import ZERO, q
from apps.core.periods import Period
from apps.onboarding.services.steps import Completeness, completeness
from apps.personal.services.availability import Availability, unpaid_fixed_items
from apps.personal.services.types import LineKind, PlanStatus
from apps.planning.models import PlanVersion
from apps.workspaces.models import Workspace

UPCOMING_DAYS = 14


@dataclass(frozen=True)
class Bar:
    label: str
    assigned: Decimal
    used: Decimal
    kind: str  # compromiso | esencial | ahorro | discrecional

    @property
    def percent(self) -> int:
        if self.assigned <= 0:
            return 100 if self.used > 0 else 0
        return int(min(self.used * 100 / self.assigned, Decimal("999")))

    @property
    def left(self) -> Decimal:
        return self.assigned - self.used

    @property
    def over(self) -> bool:
        return self.used > self.assigned


@dataclass(frozen=True)
class Upcoming:
    name: str
    date: date
    pending: Decimal


@dataclass(frozen=True)
class PersonalDashboard:
    period: Period | None
    plan_source: str | None  # aceptado | calculado
    plan_status: PlanStatus | None
    availability: Availability | None
    bars: list[Bar] = field(default_factory=list)
    upcoming: list[Upcoming] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)
    open_alerts: int = 0
    pending_proposal: PlanVersion | None = None
    profile: Completeness | None = None
    days_left: int = 0
    spending_by_group: dict[str, Decimal] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return self.availability is not None


def build_personal_dashboard(workspace: Workspace, today: date) -> PersonalDashboard:
    alerts_qs = Alert.objects.for_workspace(workspace).filter(status__in=Alert.OPEN)
    alerts = list(alerts_qs.order_by("severity", "-updated_at")[:3])
    proposal = (
        PlanVersion.objects.for_workspace(workspace)
        .filter(status__in=[PlanVersion.Status.PROPUESTA, PlanVersion.Status.GENERANDO])
        .first()
    )
    profile = completeness(workspace)
    ctx = build_context(workspace, today)
    if ctx is None:
        return PersonalDashboard(
            period=None,
            plan_source=None,
            plan_status=None,
            availability=None,
            alerts=alerts,
            open_alerts=alerts_qs.count(),
            pending_proposal=proposal,
            profile=profile,
        )

    plan, spent = ctx.plan, ctx.spent
    named = {k: v for k, v in spent.items() if k is not None}
    unpaid = unpaid_fixed_items(plan, named, today)
    fixed_total = plan.total(LineKind.COMPROMISO, LineKind.DEUDA)
    fixed_pending = sum((left for _, left in unpaid), ZERO)

    bars: list[Bar] = []
    if fixed_total > 0:
        bars.append(
            Bar("Compromisos y deudas", fixed_total, fixed_total - fixed_pending, "compromiso")
        )
    for line in plan.lines:
        if line.kind == LineKind.ESENCIAL:
            bars.append(Bar(line.name, line.amount, spent.get(line.category_ref, ZERO), "esencial"))
    leisure_spent = sum((spent.get(r, ZERO) for r in ctx.discretionary_refs), ZERO)
    leisure_spent += spent.get(None, ZERO)
    leisure = plan.total(LineKind.DISCRECIONAL)
    if leisure > 0 or leisure_spent > 0:
        bars.append(Bar("Ocio y gastos personales", leisure, leisure_spent, DISCRETIONARY_REF))
    savings = plan.total(LineKind.AHORRO)
    if savings > 0:
        bars.append(Bar("Ahorro", savings, ctx.availability.savings_contributed, "ahorro"))

    names = {line.ref: line.name for line in plan.lines}
    horizon = today + timedelta(days=UPCOMING_DAYS)
    upcoming = [
        Upcoming(names.get(item.ref, "Pago"), item.date, left)
        for item, left in unpaid
        if left > 0 and item.date <= horizon
    ]

    essential_refs = {ln.category_ref for ln in plan.lines if ln.kind == LineKind.ESENCIAL}
    by_group = {
        "Compromisos": q(fixed_total - fixed_pending),
        "Esenciales": q(sum((v for k, v in spent.items() if k in essential_refs), ZERO)),
        "Ocio": q(leisure_spent),
    }
    return PersonalDashboard(
        period=plan.period,
        plan_source=ctx.plan_source,
        plan_status=plan.status,
        availability=ctx.availability,
        bars=bars,
        upcoming=upcoming,
        alerts=alerts,
        open_alerts=alerts_qs.count(),
        pending_proposal=proposal,
        profile=profile,
        days_left=max((plan.period.end - today).days + 1, 0),
        spending_by_group={k: v for k, v in by_group.items() if v > 0},
    )
