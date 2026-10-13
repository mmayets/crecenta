"""Pantallas de la Fase 3: inventario, compras de mercancía, edición de ventas y reportes."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.business.models import InventoryMovement, Product, Purchase, Receivable, Sale
from apps.business.services.inventory import count_stock, delete_movement, register_adjustment
from apps.business.services.loaders import inventory_value
from apps.business.services.purchases import delete_purchase, register_purchase
from apps.business.services.sales import edit_sale, stock_warnings
from apps.core.dates import clamp_day
from apps.reports.services.business_reports import (
    month_label,
    monthly_statements,
    statements_csv,
    tax_summary,
)
from apps.workspaces.models import Workspace

from .forms import SALE_ROWS, PurchaseForm, SaleForm, StockActionForm
from .views import _errors, _get, business_only, business_seller

# ---------------------------------------------------------------------------- inventario


@business_seller
@require_GET
def inventory(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    products = Product.objects.for_workspace(workspace).filter(tracks_inventory=True)
    rows = [
        {
            "product": p,
            "value": max(p.stock, Decimal("0")) * p.average_cost,
            "low": p.stock_minimum > 0 and 0 <= p.stock <= p.stock_minimum,
        }
        for p in products
    ]
    return render(
        request,
        "business/inventory.html",
        {
            "workspace": workspace,
            "rows": rows,
            "total": inventory_value(workspace),
            "untracked": Product.objects.for_workspace(workspace)
            .filter(tracks_inventory=False, is_service=False, is_active=True)
            .exists(),
        },
    )


@business_only
@require_http_methods(["GET", "POST"])
def stock_product(request: HttpRequest, workspace: Workspace, product_id: Any) -> HttpResponse:
    product = _get(Product, workspace, product_id)
    if not product.tracks_inventory:
        messages.info(request, "Activa el control de inventario de este producto primero.")
        return redirect("business:product_edit", ws=workspace.pk, product_id=product.pk)
    form = StockActionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            if d["action"] == "contar":
                count_stock(workspace, request.user, product, d["qty"], d["date"],
                            client_uuid=d["client_uuid"])  # fmt: skip
            else:
                register_adjustment(
                    workspace, request.user, product, d["action"], d["qty"], d["date"],
                    unit_cost=d.get("unit_cost"), note=d["note"], client_uuid=d["client_uuid"],
                )  # fmt: skip
        except ValidationError as exc:
            for message in _errors(exc):
                form.add_error(None, message)
        else:
            messages.success(request, "Inventario actualizado.")
            return redirect("business:stock_product", ws=workspace.pk, product_id=product.pk)
    movements = product.movements.select_related(
        "sale_line__sale", "purchase_line__purchase"
    ).order_by("-date", "-created_at")[:50]
    return render(
        request,
        "business/stock_product.html",
        {"workspace": workspace, "product": product, "form": form, "movements": movements},
        status=400 if request.method == "POST" else 200,
    )


@business_only
@require_POST
def movement_delete(request: HttpRequest, workspace: Workspace, movement_id: Any) -> HttpResponse:
    movement = _get(InventoryMovement, workspace, movement_id)
    product_id = movement.product_id
    try:
        delete_movement(workspace, movement)
        messages.info(request, "Movimiento eliminado; la existencia se recalculó.")
    except ValidationError as exc:
        messages.error(request, " ".join(_errors(exc)))
    return redirect("business:stock_product", ws=workspace.pk, product_id=product_id)


# ---------------------------------------------------------------------------- compras


@business_only
@require_GET
def purchases(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    items = Purchase.objects.for_workspace(workspace).select_related("supplier")
    return render(
        request,
        "business/purchases.html",
        {"workspace": workspace, "purchases": items.prefetch_related("lines__product")[:100]},
    )


@business_only
@require_http_methods(["GET", "POST"])
def purchase_new(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    if not Product.objects.for_workspace(workspace).filter(tracks_inventory=True).exists():
        messages.info(
            request, "Primero marca qué productos compras y revendes (control de inventario)."
        )
        return redirect("business:products", ws=workspace.pk)
    form = PurchaseForm(request.POST or None, workspace=workspace)
    if request.method == "POST" and form.is_valid():
        try:
            purchase, created = register_purchase(workspace, request.user, form.to_purchase_data())
        except ValidationError as exc:
            for message in _errors(exc):
                form.add_error(None, message)
        else:
            if created:
                messages.success(request, "Compra registrada: el inventario se actualizó.")
            return redirect("business:purchase_detail", ws=workspace.pk, purchase_id=purchase.pk)
    return render(
        request,
        "business/purchase_new.html",
        {"workspace": workspace, "form": form},
        status=400 if request.method == "POST" else 200,
    )


@business_only
@require_GET
def purchase_detail(request: HttpRequest, workspace: Workspace, purchase_id: Any) -> HttpResponse:
    purchase = _get(Purchase, workspace, purchase_id)
    return render(
        request,
        "business/purchase_detail.html",
        {
            "workspace": workspace,
            "purchase": purchase,
            "lines": purchase.lines.select_related("product"),
            "payable": getattr(purchase, "payable", None),
        },
    )


@business_only
@require_POST
def purchase_delete(request: HttpRequest, workspace: Workspace, purchase_id: Any) -> HttpResponse:
    purchase = _get(Purchase, workspace, purchase_id)
    try:
        delete_purchase(workspace, purchase)
    except ValidationError as exc:
        messages.error(request, " ".join(_errors(exc)))
        return redirect("business:purchase_detail", ws=workspace.pk, purchase_id=purchase.pk)
    messages.info(request, "Compra anulada; el inventario se recalculó.")
    return redirect("business:purchases", ws=workspace.pk)


# ---------------------------------------------------------------------------- editar venta


def _sale_initial(sale: Sale) -> dict[str, Any]:
    initial: dict[str, Any] = {
        "date": sale.date,
        "payment": sale.payment,
        "account": sale.account_id,
        "customer_name": sale.customer.name if sale.customer else "",
        "apply_tax": sale.tax > 0,
        "note": sale.note,
        "client_uuid": sale.client_uuid,
    }
    receivable = Receivable.objects.filter(sale=sale).first()
    if receivable:
        initial["due_date"] = receivable.due_date
    for i, line in enumerate(sale.lines.all()[:SALE_ROWS], start=1):
        initial[f"producto_{i}"] = line.product_id
        initial[f"cantidad_{i}"] = line.qty
        initial[f"precio_{i}"] = line.unit_price
        initial[f"descuento_{i}"] = (line.discount_pct * 100).quantize(Decimal("0.01"))
    return initial


@business_only
@require_http_methods(["GET", "POST"])
def sale_edit(request: HttpRequest, workspace: Workspace, sale_id: Any) -> HttpResponse:
    sale = _get(Sale, workspace, sale_id)
    receivable = Receivable.objects.filter(sale=sale).first()
    if receivable and receivable.paid > 0:
        messages.error(request, "Esta venta ya tiene cobros: no se puede editar.")
        return redirect("business:sale_detail", ws=workspace.pk, sale_id=sale.pk)
    if sale.lines.filter(product__isnull=True).exists() or sale.lines.count() > SALE_ROWS:
        messages.error(
            request, "Esta venta no se puede editar aquí: anúlala y regístrala de nuevo."
        )
        return redirect("business:sale_detail", ws=workspace.pk, sale_id=sale.pk)
    form = SaleForm(request.POST or None, workspace=workspace, initial=_sale_initial(sale))
    if request.method == "POST" and form.is_valid():
        try:
            sale = edit_sale(workspace, request.user, sale, form.to_sale_data())
        except ValidationError as exc:
            for message in _errors(exc):
                form.add_error(None, message)
        else:
            messages.success(request, "Venta actualizada.")
            for warning in stock_warnings(sale):
                messages.warning(request, warning)
            return redirect("business:sale_detail", ws=workspace.pk, sale_id=sale.pk)
    return render(
        request,
        "business/sale_new.html",
        {"workspace": workspace, "form": form, "editing": sale},
        status=400 if request.method == "POST" else 200,
    )


# ---------------------------------------------------------------------------- reportes


def _month_from(request: HttpRequest, today: datetime.date) -> tuple[datetime.date, datetime.date]:
    raw = request.GET.get("mes", "")
    try:
        year, month = (int(x) for x in raw.split("-"))
        start = datetime.date(year, month, 1)
    except (ValueError, TypeError):
        start = today.replace(day=1)
    if start > today:
        start = today.replace(day=1)
    end = min(clamp_day(start.year, start.month, 31), today)
    return start, end


@business_only
@require_GET
def reports(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    today = timezone.localdate()
    months = monthly_statements(workspace, today)
    start, end = _month_from(request, today)
    chart = {
        "labels": [month_label(m.start) for m in months],
        "series": [
            {"name": "Ventas", "data": [float(m.sales) for m in months]},
            {"name": "Ganancia (resultado)", "data": [float(m.operating_result) for m in months]},
            {"name": "Flujo de efectivo", "data": [float(m.net_cash_flow) for m in months]},
        ],
    }
    return render(
        request,
        "business/reports.html",
        {
            "workspace": workspace,
            "months": months,
            "chart": chart,
            "tax": tax_summary(workspace, start, end),
            "tax_month": month_label(start),
            "month_options": [(m.start.strftime("%Y-%m"), month_label(m.start)) for m in months],
            "selected": start.strftime("%Y-%m"),
        },
    )


@business_only
@require_GET
def reports_csv(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    months = monthly_statements(workspace, timezone.localdate(), months=12)
    response = HttpResponse("﻿" + statements_csv(months), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="crecenta-resultados.csv"'
    return response
