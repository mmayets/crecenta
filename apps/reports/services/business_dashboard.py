"""Inicio de un espacio de negocio: las cuatro preguntas del encargo.

¿Cuánto vendí? ¿Cuánto me costó vender? ¿Cuánto gané? ¿Cuánto dinero puedo utilizar? — más lo
pendiente (por cobrar y por pagar), los productos por margen, alertas y avance de objetivos. Todo
sale de servicios ya probados; aquí solo se agrupa.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from apps.alerts.models import Alert
from apps.business.models import BusinessGoal, DebtStatus, Payable, Receivable
from apps.business.services.loaders import BusinessSnapshot, business_snapshot
from apps.onboarding.services.steps import Completeness, completeness
from apps.planning.models import PlanVersion
from apps.pricing.services.engine import MatrixCell, volume_margin_matrix
from apps.workspaces.models import Workspace

UPCOMING_DAYS = 14


@dataclass(frozen=True)
class BusinessDashboard:
    ready: bool
    profile: Completeness
    snapshot: BusinessSnapshot
    matrix: list[MatrixCell]
    receivables: list[Receivable]  # abiertas, por vencimiento
    payables: list[Payable]
    alerts: list[Alert]
    accepted_plan: PlanVersion | None
    pending_proposal: PlanVersion | None
    today: date

    @property
    def usable(self) -> Decimal:
        """Dinero que puedes utilizar: efectivo − compromisos de 30 días − reserva (≥ 0)."""
        return self.snapshot.cash.reserve.max_safe_withdrawal


def build_business_dashboard(workspace: Workspace, today: date) -> BusinessDashboard:
    profile = completeness(workspace)
    snapshot = business_snapshot(workspace, today)
    goal = BusinessGoal.objects.filter(workspace=workspace).first()
    matrix = volume_margin_matrix(
        [p.as_stats() for p in snapshot.indicators.by_product],
        goal.target_margin_pct if goal else None,
    )
    horizon = today + timedelta(days=UPCOMING_DAYS)

    def open_debts(model: type[Receivable] | type[Payable]) -> list[Any]:
        return list(
            model.objects.for_workspace(workspace)
            .exclude(status=DebtStatus.PAGADA)
            .filter(due_date__lte=horizon)
            .order_by("due_date")[:5]
        ) + list(
            model.objects.for_workspace(workspace)
            .exclude(status=DebtStatus.PAGADA)
            .filter(due_date__isnull=True)[:2]
        )

    plans = PlanVersion.objects.for_workspace(workspace).filter(
        period_start=snapshot.indicators.start
    )
    return BusinessDashboard(
        ready=profile.minimum_ready,
        profile=profile,
        snapshot=snapshot,
        matrix=matrix,
        receivables=open_debts(Receivable),
        payables=open_debts(Payable),
        alerts=list(Alert.objects.for_workspace(workspace).filter(status__in=Alert.OPEN)[:3]),
        accepted_plan=plans.filter(status=PlanVersion.Status.ACEPTADO).first(),
        pending_proposal=plans.filter(status=PlanVersion.Status.PROPUESTA).first(),
        today=today,
    )


@dataclass(frozen=True)
class SellerDashboard:
    """Inicio del vendedor: lo que vendió y lo que falta cobrar; sin costos ni ganancias."""

    today: date
    sales_today_count: int
    sales_today_total: Decimal
    my_sales_today_total: Decimal
    receivables: list[Receivable]
    low_stock: list[tuple[str, Decimal]]


def build_seller_dashboard(workspace: Workspace, user: Any, today: date) -> SellerDashboard:
    from django.db.models import Count, Q, Sum

    from apps.business.models import Product, Sale

    agg = (
        Sale.objects.for_workspace(workspace)
        .filter(date=today)
        .aggregate(
            n=Count("id"),
            amount=Sum("total", default=Decimal("0")),
            mine=Sum("total", filter=Q(created_by=user), default=Decimal("0")),
        )
    )
    low = [
        (p.name, p.stock)
        for p in Product.objects.for_workspace(workspace).filter(
            tracks_inventory=True, is_active=True, is_supply=False
        )
        if p.stock <= p.stock_minimum
    ]
    return SellerDashboard(
        today=today,
        sales_today_count=agg["n"],
        sales_today_total=agg["amount"],
        my_sales_today_total=agg["mine"],
        receivables=list(
            Receivable.objects.for_workspace(workspace)
            .exclude(status=DebtStatus.PAGADA)
            .select_related("customer")
            .order_by("due_date")[:8]
        ),
        low_stock=low,
    )
