"""Estadísticas del panel de administración: uso, comportamiento y cifras financieras agregadas.

Las cifras financieras son totales de todos los espacios, separados por moneda; nunca se
muestran los datos de una persona concreta.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import ExtractHour, TruncDate, TruncMonth
from django.utils import timezone

from apps.accounts.models import User
from apps.ai.models import AIInteraction
from apps.backoffice.models import AuditEvent
from apps.backoffice.services.audit import describe, section_for
from apps.business.models import Sale, SaleLine
from apps.ledger.choices import Direction, TxKind
from apps.ledger.models import Transaction
from apps.planning.models import PlanVersion
from apps.workspaces.models import Workspace

ZERO = Decimal("0")
Kind = AuditEvent.Kind
# Movimientos que no son ingreso ni gasto del resultado (mueven dinero entre bolsillos propios).
NOT_RESULT = {
    TxKind.TRANSFERENCIA_INTERNA, TxKind.RETIRO_EFECTIVO, TxKind.PRESTAMO, TxKind.VENTA,
    TxKind.COBRO_CXC, TxKind.PAGO_CXP, TxKind.APORTE_PROPIETARIO, TxKind.RETIRO_PROPIETARIO,
}  # fmt: skip


def _days(today: date, days: int) -> list[date]:
    return [today - timedelta(days=days - 1 - i) for i in range(days)]


def _series(rows, days: list[date], key: str = "n") -> list[int]:
    by_day = {r["day"]: r[key] for r in rows}
    return [by_day.get(d, 0) for d in days]


def usage(days: int = 30) -> dict[str, Any]:
    now = timezone.now()
    today = timezone.localdate()
    since = now - timedelta(days=days)
    span = _days(today, days)
    events = AuditEvent.objects.filter(created_at__gte=since)

    def per_day(qs, field="id", distinct=False):
        return _series(
            qs.annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(n=Count(field, distinct=distinct)),
            span,
        )

    ai = AIInteraction.objects.filter(created_at__gte=since)
    return {
        "days": days,
        "labels": [d.strftime("%d/%m") for d in span],
        "users_total": User.objects.count(),
        "users_new": User.objects.filter(date_joined__gte=since).count(),
        "active_7": events.filter(created_at__gte=now - timedelta(days=7), user__isnull=False)
        .values("user")
        .distinct()
        .count(),
        "active_30": events.filter(user__isnull=False).values("user").distinct().count(),
        "ai_consent": User.objects.filter(ai_consent=True).count(),
        "workspaces": dict(Workspace.objects.values_list("kind").annotate(n=Count("id"))),
        "events_total": events.count(),
        "failed_logins": events.filter(action="inicio_fallido").count(),
        "series": {
            "activos": per_day(events.filter(user__isnull=False), "user", distinct=True),
            "registros": _series(
                User.objects.filter(date_joined__gte=since)
                .annotate(day=TruncDate("date_joined"))
                .values("day")
                .annotate(n=Count("id")),
                span,
            ),
            "acciones": per_day(events.filter(kind=Kind.ACCION)),
            "ia": per_day(ai),
        },
        "ai_total": ai.count(),
        "ai_by_outcome": list(ai.values("outcome").annotate(n=Count("id")).order_by("-n")),
        "ai_by_purpose": list(
            ai.values("purpose")
            .annotate(
                n=Count("id"),
                tokens=Sum(F("prompt_tokens") + F("completion_tokens")),
                ok=Count("id", filter=Q(schema_valid=True)),
            )
            .order_by("-n")
        ),
        "ai_tokens": ai.aggregate(
            entrada=Sum("prompt_tokens", default=0), salida=Sum("completion_tokens", default=0)
        ),
    }


def behavior(days: int = 30) -> dict[str, Any]:
    since = timezone.now() - timedelta(days=days)
    events = AuditEvent.objects.filter(created_at__gte=since, user__isnull=False)
    sections: Counter[str] = Counter()
    for row in events.filter(kind=Kind.VISITA).values("action").annotate(n=Count("id")):
        sections[section_for(row["action"])] += row["n"]
    actions = [
        {"action": r["action"], "label": describe(r["action"], Kind.ACCION), "n": r["n"]}
        for r in events.filter(kind=Kind.ACCION)
        .values("action")
        .annotate(n=Count("id"))
        .order_by("-n")[:12]
    ]
    hours = {r["hour"]: r["n"] for r in events.annotate(hour=ExtractHour("created_at"))
             .values("hour").annotate(n=Count("id"))}  # fmt: skip
    users = User.objects.count()
    with_space = User.objects.filter(owned_workspaces__isnull=False).distinct().count()
    with_tx = Transaction.objects.values("workspace__owner").distinct().count() if users else 0
    with_plan = (
        PlanVersion.objects.filter(status=PlanVersion.Status.ACEPTADO)
        .values("workspace__owner")
        .distinct()
        .count()
    )
    return {
        "sections": sections.most_common(),
        "sections_max": max(sections.values(), default=0),
        "actions": actions,
        "actions_max": max((a["n"] for a in actions), default=0),
        "hours": [hours.get(h, 0) for h in range(24)],
        "funnel": [
            ("Se registraron", users),
            ("Crearon un espacio", with_space),
            ("Registraron movimientos", with_tx),
            ("Aceptaron un plan", with_plan),
        ],
    }


def finances(months: int = 6) -> dict[str, Any]:
    """Totales mensuales de todos los espacios, por moneda (personal y negocio por separado)."""
    today = timezone.localdate()
    start = (today.replace(day=1) - timedelta(days=31 * (months - 1))).replace(day=1)
    result_tx = Transaction.objects.filter(date__gte=start).exclude(kind__in=NOT_RESULT)

    def monthly(qs, date_field: str, value, currency_field: str):
        rows = (
            qs.annotate(month=TruncMonth(date_field))
            .values("month", currency_field)
            .annotate(total=Sum(value))
        )
        return {(r["month"], r[currency_field]): r["total"] or ZERO for r in rows}

    personal = result_tx.filter(workspace__kind=Workspace.Kind.PERSONAL)
    # En el negocio, la mercancía comprada entra al costo cuando se vende (no al comprarla).
    business = result_tx.filter(workspace__kind=Workspace.Kind.BUSINESS).exclude(
        kind=TxKind.COMPRA_INVENTARIO
    )
    p_in = monthly(personal.filter(direction=Direction.IN), "date", "amount", "workspace__currency")
    p_out = monthly(
        personal.filter(direction=Direction.OUT), "date", "amount", "workspace__currency"
    )
    b_out = monthly(
        business.filter(direction=Direction.OUT), "date", "amount", "workspace__currency"
    )
    sales = monthly(Sale.objects.filter(date__gte=start), "date", "subtotal", "workspace__currency")
    cogs = monthly(
        SaleLine.objects.filter(sale__date__gte=start),
        "sale__date",
        F("qty") * F("unit_cost_snapshot"),
        "sale__workspace__currency",
    )
    currencies = sorted({c for (_, c) in [*p_in, *p_out, *sales, *b_out]} or {"DOP"})
    month_list = []
    cursor = start
    while cursor <= today:
        month_list.append(cursor)
        cursor = (cursor + timedelta(days=32)).replace(day=1)
    tables = []
    for currency in currencies:
        rows = []
        for month in month_list:
            key = (month, currency)
            sold, cost, spent = sales.get(key, ZERO), cogs.get(key, ZERO), b_out.get(key, ZERO)
            rows.append(
                {
                    "month": month,
                    "p_in": p_in.get(key, ZERO),
                    "p_out": p_out.get(key, ZERO),
                    "p_net": p_in.get(key, ZERO) - p_out.get(key, ZERO),
                    "sales": sold,
                    "cogs": cost,
                    "b_out": spent,
                    "b_result": sold - cost - spent,
                }
            )
        tables.append(
            {
                "currency": currency,
                "rows": rows,
                "chart": {
                    "labels": [m.strftime("%m/%Y") for m in month_list],
                    "series": [
                        {"name": "Ingresos personales", "data": [float(r["p_in"]) for r in rows]},
                        {"name": "Gastos personales", "data": [float(r["p_out"]) for r in rows]},
                        {"name": "Ventas de negocios", "data": [float(r["sales"]) for r in rows]},
                    ],
                },
            }
        )
    return {
        "tables": tables,
        "plans_accepted": PlanVersion.objects.filter(status=PlanVersion.Status.ACEPTADO).count(),
        "workspaces_with_sales": Sale.objects.values("workspace").distinct().count(),
    }
