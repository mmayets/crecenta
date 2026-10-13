"""Reportes del negocio por mes (Fase 3): estado de resultados y flujo de efectivo de los últimos
meses, resumen de ITBIS y exportación CSV. Cada mes sale de los mismos indicadores de la Fase 2,
así que las cifras coinciden con el inicio."""

from __future__ import annotations

import csv
import datetime
import io
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.db.models import QuerySet, Sum

from apps.business.models import Purchase, Sale
from apps.business.services.indicators import PeriodIndicators, compute_indicators
from apps.business.services.loaders import load_business_inputs
from apps.core.dates import add_months, clamp_day
from apps.core.money import ZERO
from apps.ledger.choices import Direction
from apps.ledger.services.balances import confirmed
from apps.workspaces.models import Workspace

MONTHS = [
    "ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic",
]  # fmt: skip


def month_label(start: datetime.date) -> str:
    return f"{MONTHS[start.month - 1]} {start.year}"


def last_months(today: datetime.date, count: int) -> list[tuple[datetime.date, datetime.date]]:
    """Meses calendario del más antiguo al actual; el actual termina hoy."""
    result = []
    for back in range(count - 1, -1, -1):
        year, month = add_months(today.year, today.month, -back)
        start = datetime.date(year, month, 1)
        end = today if back == 0 else clamp_day(year, month, 31)
        result.append((start, end))
    return result


def monthly_statements(
    workspace: Workspace, today: datetime.date, months: int = 6
) -> list[PeriodIndicators]:
    return [
        compute_indicators(load_business_inputs(workspace, start, end, today))
        for start, end in last_months(today, months)
    ]


@dataclass(frozen=True)
class TaxSummary:
    collected: Decimal  # ITBIS cobrado en ventas
    paid_purchases: Decimal  # ITBIS pagado en compras de mercancía
    paid_expenses: Decimal  # ITBIS de gastos con comprobante
    note: str = (
        "Estimado informativo: no reemplaza la declaración ante la DGII ni considera "
        "retenciones, comprobantes no válidos o saldos a favor anteriores."
    )

    @property
    def paid(self) -> Decimal:
        return self.paid_purchases + self.paid_expenses

    @property
    def balance(self) -> Decimal:
        """Positivo: estimado por pagar. Negativo: estimado a favor."""
        return self.collected - self.paid


def tax_summary(workspace: Workspace, start: datetime.date, end: datetime.date) -> TaxSummary:
    def total(qs: QuerySet[Any], field: str) -> Decimal:
        value: Decimal = qs.aggregate(t=Sum(field, default=ZERO))["t"]
        return value

    return TaxSummary(
        collected=total(
            Sale.objects.for_workspace(workspace).filter(date__range=(start, end)), "tax"
        ),
        paid_purchases=total(
            Purchase.objects.for_workspace(workspace).filter(date__range=(start, end)), "tax"
        ),
        paid_expenses=total(
            confirmed(workspace).filter(
                date__range=(start, end), direction=Direction.OUT, purchase__isnull=True
            ),
            "tax_amount",
        ),
    )


CSV_COLUMNS = [
    ("Mes", lambda m: month_label(m.start)),
    ("Ventas sin ITBIS", lambda m: m.sales),
    ("Costo de lo vendido", lambda m: m.cogs),
    ("Ganancia bruta", lambda m: m.gross_profit),
    ("Margen bruto %", lambda m: m.gross_margin_pct),
    ("Gastos operativos", lambda m: m.operating_expenses),
    ("Mermas y ajustes", lambda m: m.shrinkage),
    ("Resultado", lambda m: m.operating_result),
    ("Entró a las cuentas", lambda m: m.cash_in),
    ("Salió de las cuentas", lambda m: m.cash_out),
    ("Flujo de efectivo", lambda m: m.net_cash_flow),
    ("ITBIS cobrado", lambda m: m.tax_collected),
]


def statements_csv(statements: Iterable[PeriodIndicators]) -> str:
    """CSV con punto decimal y sin separador de miles (se abre bien en Excel y Sheets)."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([name for name, _ in CSV_COLUMNS])
    for month in statements:
        writer.writerow([str(get(month)) for _, get in CSV_COLUMNS])
    return out.getvalue()
