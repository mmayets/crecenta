"""Evaluación de alertas de un espacio: arma el contexto desde la base de datos, aplica las reglas
y guarda el resultado sin duplicar.

- La misma situación (misma `dedupe_key`) actualiza la alerta abierta en lugar de crear otra.
- Una alerta descartada por la persona no vuelve a aparecer en el período.
- Una alerta abierta cuya condición ya no se cumple pasa a `resuelta` (salvo las informativas).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.alerts.models import Alert, AlertRule
from apps.alerts.services.rules_business import (
    BUSINESS_AUTO_RESOLVE,
    BUSINESS_DEFAULT_PARAMS,
    BUSINESS_RULE_LABELS,
    BusinessAlertContext,
    Withdrawal,
    evaluate_business,
)
from apps.alerts.services.rules_personal import (
    AUTO_RESOLVE,
    DEFAULT_PARAMS,
    RULE_LABELS,
    AlertDraft,
    PersonalAlertContext,
    check_purchase_impact,
    evaluate_personal,
)
from apps.business.models import BusinessGoal
from apps.business.services.indicators import compute_indicators
from apps.business.services.loaders import (
    load_business_inputs,
    load_cash_outlook,
    month_bounds,
)
from apps.core.dates import add_months, clamp_day
from apps.ledger.choices import CategoryGroup, Direction, TxKind
from apps.ledger.models import Category
from apps.ledger.services.balances import confirmed, spent_by_category
from apps.personal.services.budget_engine import build_personal_plan
from apps.personal.services.loaders import load_personal_inputs, workspace_availability
from apps.planning.services.lifecycle import accepted_result
from apps.workspaces.models import Workspace

DEBOUNCE_SECONDS = 5


def catalog(workspace: Workspace) -> tuple[dict[str, dict], dict[str, str]]:
    """Reglas disponibles en el espacio (parámetros por defecto y nombres)."""
    if workspace.is_business:
        return BUSINESS_DEFAULT_PARAMS, BUSINESS_RULE_LABELS
    return DEFAULT_PARAMS, RULE_LABELS


def rule_settings(workspace: Workspace) -> tuple[frozenset[str], dict[str, dict]]:
    rules = {r.code: r for r in AlertRule.objects.for_workspace(workspace)}
    defaults, _ = catalog(workspace)
    enabled = frozenset(code for code in defaults if code not in rules or rules[code].enabled)
    params = {code: rule.params for code, rule in rules.items()}
    return enabled, params


def build_context(workspace: Workspace, today: date) -> PersonalAlertContext | None:
    """Contexto de evaluación con el plan aceptado vigente (o el calculado si no hay)."""
    plan = accepted_result(workspace, today)
    source = "aceptado"
    if plan is None:
        plan = build_personal_plan(load_personal_inputs(workspace, today), with_alternatives=False)
        source = "calculado"
    if not plan.by_pay_event:
        return None  # sin ingresos no hay plan contra el cual alertar
    spent: dict[str | None, Decimal] = {
        (str(k) if k else None): v
        for k, v in spent_by_category(workspace, plan.period.start, today).items()
    }
    discretionary = frozenset(
        str(pk)
        for pk in Category.objects.for_workspace(workspace)
        .filter(group=CategoryGroup.DISCRECIONAL)
        .values_list("id", flat=True)
    )
    enabled, params = rule_settings(workspace)
    return PersonalAlertContext(
        today=today,
        plan=plan,
        plan_source=source,
        spent=spent,
        discretionary_refs=discretionary,
        availability=workspace_availability(workspace, today, plan),
        currency=workspace.currency,
        params=params,
        enabled=enabled,
    )


def build_business_context(workspace: Workspace, today: date) -> BusinessAlertContext:
    start, _ = month_bounds(today)
    year, month = add_months(today.year, today.month, -1)
    prev_start = date(year, month, 1)
    prev_end = clamp_day(year, month, today.day)
    outlook = load_cash_outlook(workspace, today)
    withdrawals = [
        Withdrawal(d, amount)
        for d, amount in confirmed(workspace)
        .filter(
            kind=TxKind.RETIRO_PROPIETARIO,
            direction=Direction.OUT,
            date__range=(start, today),
        )
        .values_list("date", "amount")
    ]
    goal = BusinessGoal.objects.filter(workspace=workspace).first()
    enabled, params = rule_settings(workspace)
    return BusinessAlertContext(
        today=today,
        currency=workspace.currency,
        month=compute_indicators(load_business_inputs(workspace, start, today, today)),
        previous_same_days=compute_indicators(
            load_business_inputs(workspace, prev_start, prev_end, today)
        ),
        projection=outlook.projection,
        reserve=outlook.reserve,
        withdrawals=withdrawals,
        target_margin=goal.target_margin_pct if goal else None,
        params=params,
        enabled=enabled,
    )


@transaction.atomic
def persist_alerts(
    workspace: Workspace, drafts: list[AlertDraft], period_start: date
) -> list[Alert]:
    existing = {
        a.dedupe_key: a
        for a in Alert.objects.for_workspace(workspace)
        .filter(period_start=period_start)
        .select_for_update()
    }
    now = timezone.now()
    saved: list[Alert] = []
    for draft in drafts:
        alert = existing.get(draft.dedupe_key)
        if alert and alert.status == Alert.Status.DESCARTADA:
            continue
        if alert is None:
            alert = Alert(
                workspace=workspace, dedupe_key=draft.dedupe_key, period_start=period_start
            )
        elif alert.status == Alert.Status.RESUELTA:
            alert.status = Alert.Status.NUEVA  # la situación volvió a ocurrir
            alert.resolved_at = None
        alert.code = draft.code
        alert.severity = draft.severity
        alert.title = draft.title
        alert.message = draft.message
        alert.data_used = draft.data_used
        alert.is_projection = draft.is_projection
        alert.suggested_action = draft.suggested_action
        alert.save()
        saved.append(alert)

    current = {d.dedupe_key for d in drafts}
    auto = BUSINESS_AUTO_RESOLVE if workspace.is_business else AUTO_RESOLVE
    for key, alert in existing.items():
        if key not in current and alert.is_open and alert.code in auto:
            alert.status = Alert.Status.RESUELTA
            alert.resolved_at = now
            alert.save(update_fields=["status", "resolved_at", "updated_at"])
    return saved


def evaluate_workspace(workspace: Workspace, today: date | None = None) -> list[Alert]:
    today = today or timezone.localdate()
    if workspace.is_business:
        business = build_business_context(workspace, today)
        return persist_alerts(workspace, evaluate_business(business), month_bounds(today)[0])
    ctx = build_context(workspace, today)
    if ctx is None:
        return []
    return persist_alerts(workspace, evaluate_personal(ctx), ctx.plan.period.start)


def purchase_warnings(
    workspace: Workspace, amount: Decimal, category: Category | None, today: date | None = None
) -> list[AlertDraft]:
    """Avisos previos a registrar un gasto (no se guardan)."""
    if not workspace.is_personal:
        return []
    ctx = build_context(workspace, today or timezone.localdate())
    if ctx is None:
        return []
    return check_purchase_impact(ctx, amount, str(category.pk) if category else None)


def schedule_evaluation(workspace_id: object) -> None:
    """Encola una evaluación tras registrar movimientos; agrupa ráfagas (p. ej. sincronización)."""
    from apps.alerts.tasks import evaluate_workspace_task

    if cache.add(f"alerts:pending:{workspace_id}", 1, timeout=DEBOUNCE_SECONDS):
        evaluate_workspace_task.apply_async(args=[str(workspace_id)], countdown=DEBOUNCE_SECONDS)
