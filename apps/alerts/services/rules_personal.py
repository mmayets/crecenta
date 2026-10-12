"""Reglas de alertas personales (funciones puras sobre datos ya calculados).

Cada alerta explica qué pasa, con qué datos, si es proyección y qué acción se sugiere; la acción
siempre requiere que la persona la apruebe. Reglas (encargo §11):

- categoria_80: consumo ≥ umbral (80 %) del presupuesto de un esencial o del ocio;
  ≥ 100 % es urgente.
- riesgo_fin_periodo (proyección): al ritmo actual, un esencial o el ocio se pasaría antes de fin
  de período. Solo gastos variables: los compromisos fijos no se proyectan linealmente.
- pago_sin_cobertura: un pago vence en los próximos N días y el dinero de las cuentas de uso
  diario no alcanza (y no hay un cobro antes del vencimiento).
- meta_en_riesgo: no se apartó el ahorro de los cobros ya recibidos; propone repartir el faltante
  entre los próximos cobros.
- compra_afecta_reserva: los gastos ya usan dinero comprometido para pagos, ahorro o reserva.
- buen_desempeno: pasada la mitad del período, el gasto variable va por debajo de lo previsto.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from apps.core.money import ZERO, fmt, q, split_evenly
from apps.personal.services.availability import Availability, unpaid_fixed_items
from apps.personal.services.types import BudgetResult, LineKind

_MONTHS = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]  # fmt: skip

DEFAULT_PARAMS: dict[str, dict[str, Any]] = {
    "categoria_80": {"umbral_pct": 80},
    "riesgo_fin_periodo": {"dias_minimos": 3},
    "pago_sin_cobertura": {"dias_antes": 3},
    "meta_en_riesgo": {"dias_gracia": 3},
    "compra_afecta_reserva": {},
    "buen_desempeno": {"avance_minimo_pct": 50},
}
RULE_LABELS = {
    "categoria_80": "Consumo alto de una categoría",
    "riesgo_fin_periodo": "Riesgo de pasarte antes de fin de período",
    "pago_sin_cobertura": "Pago próximo sin dinero suficiente",
    "meta_en_riesgo": "Meta de ahorro atrasada",
    "compra_afecta_reserva": "Gastos que usan dinero comprometido",
    "buen_desempeno": "Buen desempeño",
}
# Se resuelven solas cuando la condición deja de cumplirse.
AUTO_RESOLVE = frozenset(DEFAULT_PARAMS) - {"buen_desempeno"}
DISCRETIONARY_REF = "discrecional"


def day_text(d: date) -> str:
    return f"{d.day} de {_MONTHS[d.month - 1]}"


@dataclass(frozen=True)
class AlertDraft:
    code: str
    severity: str  # info | media | alta
    title: str
    message: str
    dedupe_key: str
    data_used: dict[str, Any] = field(default_factory=dict)
    is_projection: bool = False
    suggested_action: dict[str, Any] | None = None


@dataclass(frozen=True)
class PersonalAlertContext:
    today: date
    plan: BudgetResult
    plan_source: str  # "aceptado" | "calculado"
    spent: dict[str | None, Decimal]  # gasto confirmado del período por categoría (ref en texto)
    discretionary_refs: frozenset[str]  # categorías del grupo discrecional
    availability: Availability
    currency: str = "DOP"
    params: dict[str, dict[str, Any]] = field(default_factory=dict)
    enabled: frozenset[str] = frozenset(DEFAULT_PARAMS)

    def param(self, code: str, name: str) -> Any:
        return {**DEFAULT_PARAMS[code], **self.params.get(code, {})}[name]

    def money(self, value: Decimal) -> str:
        return fmt(value, self.currency)

    @property
    def key(self) -> str:
        return self.plan.period.start.isoformat()


@dataclass(frozen=True)
class _Budget:
    ref: str
    name: str
    assigned: Decimal
    spent: Decimal


def _variable_budgets(ctx: PersonalAlertContext) -> list[_Budget]:
    """Presupuestos de gasto variable: cada esencial con categoría y el ocio en conjunto."""
    budgets = [
        _Budget(line.ref, line.name, line.amount, ctx.spent.get(line.category_ref, ZERO))
        for line in ctx.plan.lines
        if line.kind == LineKind.ESENCIAL and line.category_ref and line.amount > 0
    ]
    leisure = ctx.plan.total(LineKind.DISCRECIONAL)
    leisure_spent = sum((ctx.spent.get(r, ZERO) for r in ctx.discretionary_refs), ZERO)
    leisure_spent += ctx.spent.get(None, ZERO)  # gastos sin categoría cuentan como ocio
    if leisure > 0 or leisure_spent > 0:
        budgets.append(
            _Budget(DISCRETIONARY_REF, "Ocio y gastos personales", leisure, leisure_spent)
        )
    return budgets


def _base_data(ctx: PersonalAlertContext, **extra: Any) -> dict[str, Any]:
    return {
        "plan": ctx.plan_source,
        "periodo": [ctx.plan.period.start.isoformat(), ctx.plan.period.end.isoformat()],
        **{k: (str(v) if isinstance(v, Decimal) else v) for k, v in extra.items()},
    }


def category_usage(ctx: PersonalAlertContext) -> list[AlertDraft]:
    threshold = Decimal(str(ctx.param("categoria_80", "umbral_pct")))
    drafts = []
    for b in _variable_budgets(ctx):
        if b.assigned <= 0:
            if b.spent > 0:
                pct = Decimal("100")
            else:
                continue
        else:
            pct = q(b.spent * 100 / b.assigned)
        if pct < threshold:
            continue
        over = pct >= 100
        drafts.append(
            AlertDraft(
                code="categoria_80",
                severity="alta" if over else "media",
                title=(
                    f"Te pasaste del presupuesto de {b.name}"
                    if over
                    else f"Llevas el {pct}% de {b.name}"
                ),
                message=(
                    f"Has gastado {ctx.money(b.spent)} de {ctx.money(b.assigned)} "
                    f"presupuestados para {b.name} en este período."
                    + (
                        f" Te pasaste por {ctx.money(b.spent - b.assigned)}."
                        if over
                        else f" Te quedan {ctx.money(b.assigned - b.spent)}."
                    )
                ),
                dedupe_key=f"categoria_80:{ctx.key}:{b.ref}:{100 if over else 80}",
                data_used=_base_data(
                    ctx, concepto=b.name, gastado=b.spent, asignado=b.assigned, porcentaje=pct
                ),
                suggested_action={"tipo": "revisar_plan", "parametros": {"concepto": b.ref}},
            )
        )
    return drafts


def end_of_period_risk(ctx: PersonalAlertContext) -> list[AlertDraft]:
    period = ctx.plan.period
    elapsed = period.days_elapsed(ctx.today)
    remaining = period.days - elapsed
    if elapsed < ctx.param("riesgo_fin_periodo", "dias_minimos") or remaining <= 0:
        return []
    drafts = []
    for b in _variable_budgets(ctx):
        if b.spent <= 0 or b.assigned <= 0 or b.spent >= b.assigned:
            continue  # sin gasto, o ya excedido (lo cubre categoria_80)
        projected = q(b.spent * period.days / elapsed)
        if projected <= b.assigned:
            continue
        per_day = q((b.assigned - b.spent) / remaining)
        drafts.append(
            AlertDraft(
                code="riesgo_fin_periodo",
                severity="media",
                title=f"A este ritmo te pasarías en {b.name}",
                message=(
                    f"Llevas {ctx.money(b.spent)} en {elapsed} días. Si sigues igual, terminarías "
                    f"el período con {ctx.money(projected)} de {ctx.money(b.assigned)} "
                    f"presupuestados. Para no pasarte, gasta como máximo {ctx.money(per_day)} "
                    f"por día los próximos {remaining} días."
                ),
                dedupe_key=f"riesgo_fin_periodo:{ctx.key}:{b.ref}",
                data_used=_base_data(
                    ctx,
                    concepto=b.name,
                    gastado=b.spent,
                    asignado=b.assigned,
                    dias_transcurridos=elapsed,
                    dias_del_periodo=period.days,
                    proyectado=projected,
                ),
                is_projection=True,
                suggested_action={
                    "tipo": "limite_diario",
                    "parametros": {"concepto": b.ref, "monto_diario": str(per_day)},
                },
            )
        )
    return drafts


def payment_without_coverage(ctx: PersonalAlertContext) -> list[AlertDraft]:
    days = int(ctx.param("pago_sin_cobertura", "dias_antes"))
    limit = ctx.today + timedelta(days=days)
    next_pay = ctx.availability.next_pay_date
    spent = {k: v for k, v in ctx.spent.items() if k is not None}
    due = [
        (item, left)
        for item, left in unpaid_fixed_items(ctx.plan, spent, ctx.today)
        if left > 0
        and ctx.today <= item.date <= limit
        and not (next_pay and next_pay <= item.date)  # un cobro llega antes del vencimiento
    ]
    if not due:
        return []
    needed = sum((left for _, left in due), ZERO)
    available = ctx.availability.for_spending
    if available >= needed:
        return []
    names = {line.ref: line.name for line in ctx.plan.lines}
    first, _ = due[0]
    detail = ", ".join(
        f"{names.get(i.ref, 'pago')} ({ctx.money(left)}) el {day_text(i.date)}" for i, left in due
    )
    return [
        AlertDraft(
            code="pago_sin_cobertura",
            severity="alta",
            title="No te alcanza para un pago próximo",
            message=(
                f"Vence pronto: {detail}. En tus cuentas de uso diario hay {ctx.money(available)}; "
                f"faltan {ctx.money(needed - available)}."
            ),
            dedupe_key=f"pago_sin_cobertura:{ctx.key}:{first.ref}:{first.date.isoformat()}",
            data_used=_base_data(
                ctx,
                pagos=[
                    {
                        "concepto": names.get(i.ref, "pago"),
                        "fecha": i.date.isoformat(),
                        "pendiente": str(left),
                    }
                    for i, left in due
                ],
                disponible_en_cuentas=available,
                faltante=needed - available,
            ),
            suggested_action={
                "tipo": "mover_dinero",
                "parametros": {"monto": str(needed - available)},
            },
        )
    ]


def savings_at_risk(ctx: PersonalAlertContext) -> list[AlertDraft]:
    grace = timedelta(days=int(ctx.param("meta_en_riesgo", "dias_gracia")))
    expected = sum(
        (
            item.amount
            for item in ctx.plan.scheduled
            if item.kind == LineKind.AHORRO
            and item.pay_event_date is not None
            and item.pay_event_date + grace <= ctx.today
        ),
        ZERO,
    )
    shortfall = expected - ctx.availability.savings_contributed
    if shortfall <= 0:
        return []
    upcoming = [e.date for e in ctx.plan.by_pay_event if e.date > ctx.today]
    if upcoming:
        parts = split_evenly(shortfall, len(upcoming))
        proposal = [
            {"fecha": d.isoformat(), "monto": str(p)} for d, p in zip(upcoming, parts, strict=True)
        ]
        suggestion = (
            "Puedes reponerlo así: "
            + ", ".join(
                f"{ctx.money(p)} el {day_text(d)}" for d, p in zip(upcoming, parts, strict=True)
            )
            + "."
        )
    else:
        proposal = [{"fecha": "proximo_cobro", "monto": str(shortfall)}]
        suggestion = f"Puedes reponer {ctx.money(shortfall)} con tu próximo cobro."
    return [
        AlertDraft(
            code="meta_en_riesgo",
            severity="media",
            title="Tu meta de ahorro va atrasada",
            message=(
                f"Según tu plan ya deberías haber apartado {ctx.money(expected)} y llevas "
                f"{ctx.money(ctx.availability.savings_contributed)}. {suggestion}"
            ),
            dedupe_key=f"meta_en_riesgo:{ctx.key}",
            data_used=_base_data(
                ctx,
                esperado=expected,
                aportado=ctx.availability.savings_contributed,
                faltante=shortfall,
            ),
            suggested_action={"tipo": "repartir_ahorro", "parametros": {"aportes": proposal}},
        )
    ]


def committed_money_used(ctx: PersonalAlertContext) -> list[AlertDraft]:
    a = ctx.availability
    if a.spendable >= 0:
        return []
    return [
        AlertDraft(
            code="compra_afecta_reserva",
            severity="alta",
            title="Estás usando dinero comprometido",
            message=(
                f"En tus cuentas de uso diario hay {ctx.money(a.for_spending)}, pero "
                f"{ctx.money(a.committed)} ya están comprometidos (pagos pendientes "
                f"{ctx.money(a.pending_commitments)}, ahorro pendiente "
                f"{ctx.money(a.pending_savings)} y reserva {ctx.money(a.reserves)}). "
                f"Te faltan {ctx.money(-a.spendable)}."
            ),
            dedupe_key=f"compra_afecta_reserva:{ctx.key}",
            data_used=_base_data(
                ctx,
                disponible_en_cuentas=a.for_spending,
                comprometido=a.committed,
                faltante=-a.spendable,
            ),
            suggested_action={"tipo": "revisar_plan", "parametros": {}},
        )
    ]


def good_performance(ctx: PersonalAlertContext) -> list[AlertDraft]:
    period = ctx.plan.period
    elapsed = period.days_elapsed(ctx.today)
    if elapsed * 100 < period.days * ctx.param("buen_desempeno", "avance_minimo_pct"):
        return []
    if ctx.today >= period.end or ctx.availability.spendable < 0:
        return []
    budgets = _variable_budgets(ctx)
    assigned = sum((b.assigned for b in budgets), ZERO)
    spent = sum((b.spent for b in budgets), ZERO)
    expected = q(assigned * elapsed / period.days)
    if assigned <= 0 or spent > expected * Decimal("0.9"):
        return []
    if savings_at_risk(ctx):
        return []
    return [
        AlertDraft(
            code="buen_desempeno",
            severity="info",
            title="¡Vas muy bien este período!",
            message=(
                f"Llevas {ctx.money(spent)} en gastos variables y a esta fecha tu plan preveía "
                f"{ctx.money(expected)}. Sigue así."
            ),
            dedupe_key=f"buen_desempeno:{ctx.key}",
            data_used=_base_data(ctx, gastado=spent, previsto_a_la_fecha=expected),
        )
    ]


RULES = {
    "categoria_80": category_usage,
    "riesgo_fin_periodo": end_of_period_risk,
    "pago_sin_cobertura": payment_without_coverage,
    "meta_en_riesgo": savings_at_risk,
    "compra_afecta_reserva": committed_money_used,
    "buen_desempeno": good_performance,
}


def evaluate_personal(ctx: PersonalAlertContext) -> list[AlertDraft]:
    drafts: list[AlertDraft] = []
    for code, rule in RULES.items():
        if code in ctx.enabled:
            drafts.extend(rule(ctx))
    return drafts


def check_purchase_impact(
    ctx: PersonalAlertContext, amount: Decimal, category_ref: str | None
) -> list[AlertDraft]:
    """Validación al registrar un gasto (antes de guardarlo): avisa si usa dinero comprometido o
    si supera el presupuesto de su categoría. No se guarda: la persona decide."""
    warnings: list[AlertDraft] = []
    spendable = ctx.availability.spendable
    if amount > spendable:
        warnings.append(
            AlertDraft(
                code="compra_afecta_reserva",
                severity="alta",
                title="Este gasto usaría dinero comprometido",
                message=(
                    f"Según tu plan puedes gastar {ctx.money(max(spendable, ZERO))} sin tocar lo "
                    f"reservado para pagos, ahorro y reserva. Este gasto de {ctx.money(amount)} "
                    f"usaría {ctx.money(amount - max(spendable, ZERO))} de ese dinero."
                ),
                dedupe_key="previo",
                data_used=_base_data(ctx, gasto=amount, disponible_para_gastar=spendable),
            )
        )
    for b in _variable_budgets(ctx):
        matches = b.ref == DISCRETIONARY_REF and (
            category_ref is None or category_ref in ctx.discretionary_refs
        )
        line = next((ln for ln in ctx.plan.lines if ln.ref == b.ref), None)
        same_category = bool(line and category_ref and line.category_ref == category_ref)
        if (matches or same_category) and b.spent + amount > b.assigned:
            warnings.append(
                AlertDraft(
                    code="categoria_80",
                    severity="media",
                    title=f"Superarías tu presupuesto de {b.name}",
                    message=(
                        f"Llevas {ctx.money(b.spent)} de {ctx.money(b.assigned)}; con este "
                        f"gasto llegarías a {ctx.money(b.spent + amount)}."
                    ),
                    dedupe_key="previo",
                    data_used=_base_data(ctx, gastado=b.spent, asignado=b.assigned),
                )
            )
    return warnings
