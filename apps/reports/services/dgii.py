"""Archivos de apoyo 606 (compras) y 607 (ventas) para el contador (docs/fase4.md, decisión 7).

No son el envío oficial a la DGII: las columnas siguen el orden de los formatos 606 y 607 vigentes
al escribir esto, con lo que la app sabe (NCF, RNC o cédula, fecha, montos, ITBIS y forma de pago);
lo que no sabe (retenciones, ISC, propina, NCF modificado) va vacío o en cero para que el contador
lo complete. Solo entran las facturas con NCF; las demás se cuentan aparte para avisar.
"""

from __future__ import annotations

import csv
import datetime
import io
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db.models import Max

from apps.core.money import ZERO

if TYPE_CHECKING:
    from apps.business.models import Purchase, Sale
    from apps.workspaces.models import Workspace

HEADERS_607 = [
    "RNC/Cédula o Pasaporte", "Tipo Identificación", "Número Comprobante Fiscal",
    "Número Comprobante Fiscal Modificado", "Tipo de Ingreso", "Fecha Comprobante",
    "Fecha de Retención", "Monto Facturado", "ITBIS Facturado", "ITBIS Retenido por Terceros",
    "ITBIS Percibido", "Retención Renta por Terceros", "ISR Percibido",
    "Impuesto Selectivo al Consumo", "Otros Impuestos/Tasas", "Monto Propina Legal", "Efectivo",
    "Cheque/Transferencia/Depósito", "Tarjeta Débito/Crédito", "Venta a Crédito",
    "Bonos o Certificados de Regalo", "Permuta", "Otras Formas de Ventas",
]  # fmt: skip
HEADERS_606 = [
    "RNC o Cédula", "Tipo Id", "Tipo Bienes y Servicios Comprados", "NCF",
    "NCF o Documento Modificado", "Fecha Comprobante", "Fecha Pago",
    "Monto Facturado en Servicios", "Monto Facturado en Bienes", "Total Monto Facturado",
    "ITBIS Facturado", "ITBIS Retenido", "ITBIS sujeto a Proporcionalidad",
    "ITBIS llevado al Costo", "ITBIS por Adelantar", "ITBIS percibido en compras",
    "Tipo de Retención en ISR", "Monto Retención Renta", "ISR Percibido en compras",
    "Impuesto Selectivo al Consumo", "Otros Impuestos/Tasas", "Monto Propina Legal",
    "Forma de Pago",
]  # fmt: skip

INGRESO_OPERACIONES = "01"  # ingresos por operaciones (no financieros)
COMPRA_COSTO_DE_VENTA = "09"  # compras que forman parte del costo de venta
PAGO_EFECTIVO, PAGO_BANCO, PAGO_TARJETA, PAGO_CREDITO = "01", "02", "03", "04"


def id_type(tax_id: str) -> str:
    """1 = RNC (9 dígitos), 2 = cédula (11); vacío si no hay."""
    return {9: "1", 11: "2"}.get(len(tax_id), "") if tax_id else ""


def _date(value: datetime.date | None) -> str:
    return value.strftime("%Y%m%d") if value else ""


def _amount(value: Decimal) -> str:
    return f"{value:.2f}"


@dataclass(frozen=True)
class SupportFile:
    rows: list[list[str]]
    missing_ncf: int  # facturas del mes sin NCF (no entran)
    missing_tax_id: int  # con NCF pero sin RNC o cédula de la contraparte

    def to_csv(self, headers: list[str]) -> str:
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(headers)
        writer.writerows(self.rows)
        return out.getvalue()


def _sale_payment_columns(sale: Sale) -> list[str]:
    """Efectivo, banco, tarjeta, crédito, bonos, permuta, otras (el total va en una sola)."""
    columns = [ZERO] * 7
    total = sale.total
    if sale.payment == "credito":
        columns[3] = total
    else:
        kind = sale.account.type if sale.account else "efectivo"
        columns[{"efectivo": 0, "banco": 1, "billetera": 1, "tarjeta": 2}.get(kind, 6)] = total
    return [_amount(c) for c in columns]


def sales_607(workspace: Workspace, start: datetime.date, end: datetime.date) -> SupportFile:
    from apps.business.models import Sale

    month = Sale.objects.for_workspace(workspace).filter(date__range=(start, end))
    rows = []
    missing_tax_id = 0
    for sale in month.exclude(ncf="").select_related("customer", "account").order_by("date", "ncf"):
        tax_id = sale.customer.tax_id if sale.customer else ""
        missing_tax_id += not tax_id
        rows.append(
            [
                tax_id, id_type(tax_id), sale.ncf, "", INGRESO_OPERACIONES, _date(sale.date), "",
                _amount(sale.subtotal), _amount(sale.tax), "0.00", "0.00", "0.00", "0.00",
                "0.00", "0.00", "0.00", *_sale_payment_columns(sale),
            ]
        )  # fmt: skip
    return SupportFile(rows, month.filter(ncf="").count(), missing_tax_id)


def _purchase_payment(purchase: Purchase) -> tuple[str, datetime.date | None]:
    """Forma de pago y fecha de pago (crédito: la del último pago, si ya se pagó completa)."""
    from apps.business.models import DebtStatus, Payable
    from apps.ledger.models import Transaction

    if purchase.payment == "credito":
        payable = Payable.objects.filter(purchase=purchase).first()
        paid_on = None
        if payable is not None and payable.status == DebtStatus.PAGADA:
            paid_on = Transaction.objects.filter(payable=payable).aggregate(d=Max("date"))["d"]
        return PAGO_CREDITO, paid_on
    kind = purchase.account.type if purchase.account else "efectivo"
    code = {"efectivo": PAGO_EFECTIVO, "tarjeta": PAGO_TARJETA}.get(kind, PAGO_BANCO)
    return code, purchase.date


def purchases_606(workspace: Workspace, start: datetime.date, end: datetime.date) -> SupportFile:
    from apps.business.models import Purchase

    month = Purchase.objects.for_workspace(workspace).filter(date__range=(start, end))
    rows = []
    missing_tax_id = 0
    for purchase in (
        month.exclude(ncf="").select_related("supplier", "account").order_by("date", "ncf")
    ):
        tax_id = purchase.supplier.tax_id if purchase.supplier else ""
        missing_tax_id += not tax_id
        payment, paid_on = _purchase_payment(purchase)
        rows.append(
            [
                tax_id, id_type(tax_id), COMPRA_COSTO_DE_VENTA, purchase.ncf, "",
                _date(purchase.date), _date(paid_on), "0.00", _amount(purchase.subtotal),
                _amount(purchase.subtotal), _amount(purchase.tax), "0.00", "0.00", "0.00",
                _amount(purchase.tax), "0.00", "", "0.00", "0.00", "0.00", "0.00", "0.00",
                payment,
            ]
        )  # fmt: skip
    return SupportFile(rows, month.filter(ncf="").count(), missing_tax_id)


def totals(file: SupportFile, amount_col: int, tax_col: int) -> tuple[Decimal, Decimal]:
    """Suma de monto facturado e ITBIS de las filas (para mostrar en pantalla)."""
    amount = sum((Decimal(r[amount_col]) for r in file.rows), ZERO)
    tax = sum((Decimal(r[tax_col]) for r in file.rows), ZERO)
    return amount, tax
