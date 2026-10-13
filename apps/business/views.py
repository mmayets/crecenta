"""Pantallas del negocio: ventas, productos y costos, calculadora de precios, por cobrar y por
pagar, y dinero del propietario. Todas las cifras salen de los servicios."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.business.models import (
    BusinessGoal,
    BusinessProfile,
    DebtStatus,
    OperatingExpense,
    Payable,
    Product,
    Receivable,
    Sale,
)
from apps.business.services.cash import check_withdrawal
from apps.business.services.costs import refresh_unit_cost
from apps.business.services.indicators import MONTHLY_FACTOR
from apps.business.services.loaders import load_cash_outlook, month_bounds
from apps.business.services.sales import (
    collect_receivable,
    delete_sale,
    pay_payable,
    register_payable,
    register_receivable,
    register_sale,
)
from apps.onboarding.business_forms import ProductForm
from apps.pricing.services.engine import (
    PricingInputs,
    break_even_units,
    compute_price,
    margin_after_discount,
    service_capacity,
    supplier_increase,
    unit_economics,
)
from apps.pricing.services.loaders import inputs_for_product
from apps.workspaces.mixins import workspace_required
from apps.workspaces.models import Workspace
from apps.workspaces.services.transfers import transfer_between

from .forms import ComponentFormSet, DebtForm, OwnerForm, PricingForm, SaleForm, SettleForm

HUNDRED = Decimal("100")
business_only = workspace_required(kind="business")


def _get(model: Any, workspace: Workspace, pk: Any) -> Any:
    try:
        return model.objects.for_workspace(workspace).get(pk=pk)
    except (model.DoesNotExist, ValidationError, ValueError) as exc:
        raise Http404("No encontrado") from exc


def _errors(exc: ValidationError) -> list[str]:
    return exc.messages


# ---------------------------------------------------------------------------- ventas


@business_only
@require_GET
def sales(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    start, end = month_bounds(timezone.localdate())
    month = Sale.objects.for_workspace(workspace).filter(date__range=(start, end))
    totals = month.aggregate(subtotal=Sum("subtotal"), total=Sum("total"))
    return render(
        request,
        "business/sales.html",
        {
            "workspace": workspace,
            "sales": month.select_related("customer").prefetch_related("lines")[:100],
            "totals": totals,
            "start": start,
        },
    )


@business_only
@require_http_methods(["GET", "POST"])
def sale_new(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    form = SaleForm(request.POST or None, workspace=workspace)
    if not Product.objects.for_workspace(workspace).filter(is_active=True).exists():
        messages.info(request, "Primero registra lo que vendes.")
        return redirect("business:product_new", ws=workspace.pk)
    if request.method == "POST" and form.is_valid():
        try:
            sale, created = register_sale(workspace, request.user, form.to_sale_data())
        except ValidationError as exc:
            for message in _errors(exc):
                form.add_error(None, message)
        else:
            if created:
                messages.success(request, "Venta registrada.")
            return redirect("business:sale_detail", ws=workspace.pk, sale_id=sale.pk)
    return render(
        request,
        "business/sale_new.html",
        {"workspace": workspace, "form": form},
        status=400 if request.method == "POST" else 200,
    )


@business_only
@require_GET
def sale_detail(request: HttpRequest, workspace: Workspace, sale_id: Any) -> HttpResponse:
    sale = _get(Sale, workspace, sale_id)
    lines = list(sale.lines.select_related("product"))
    cost = sum((line.qty * line.unit_cost_snapshot for line in lines), Decimal("0"))
    return render(
        request,
        "business/sale_detail.html",
        {
            "workspace": workspace,
            "sale": sale,
            "lines": lines,
            "cost": cost,
            "profit": sale.subtotal - cost,
            "receivable": Receivable.objects.filter(sale=sale).first(),
        },
    )


@business_only
@require_POST
def sale_delete(request: HttpRequest, workspace: Workspace, sale_id: Any) -> HttpResponse:
    sale = _get(Sale, workspace, sale_id)
    try:
        delete_sale(workspace, sale)
    except ValidationError as exc:
        messages.error(request, " ".join(_errors(exc)))
        return redirect("business:sale_detail", ws=workspace.pk, sale_id=sale.pk)
    messages.info(request, "Venta anulada.")
    return redirect("business:sales", ws=workspace.pk)


# ---------------------------------------------------------------------------- productos


@business_only
@require_GET
def products(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    goal = BusinessGoal.objects.filter(workspace=workspace).first()
    profile = BusinessProfile.objects.filter(workspace=workspace).first()
    target = goal.target_margin_pct if goal and goal.target_margin_pct is not None else None
    rows = []
    for product in Product.objects.for_workspace(workspace).prefetch_related("components"):
        inputs = inputs_for_product(product, profile, target or Decimal("0.30"))
        economics = unit_economics(product.price, inputs.unit_cost, inputs.commission_pct)
        suggested = compute_price(inputs).net_price if target is not None else None
        rows.append({"product": product, "economics": economics, "suggested": suggested})
    rows.sort(key=lambda r: (r["economics"].margin_pct, r["product"].name))
    expenses = OperatingExpense.objects.for_workspace(workspace).filter(is_active=True)
    return render(
        request,
        "business/products.html",
        {
            "workspace": workspace,
            "rows": rows,
            "target": target * HUNDRED if target is not None else None,
            "expenses": expenses,
        },
    )


@business_only
@require_http_methods(["GET", "POST"])
def product_edit(
    request: HttpRequest, workspace: Workspace, product_id: Any = None
) -> HttpResponse:
    product = _get(Product, workspace, product_id) if product_id else Product(workspace=workspace)
    form = ProductForm(request.POST or None, instance=product, workspace=workspace)
    components = ComponentFormSet(request.POST or None, instance=product, prefix="componentes")
    if request.method == "POST" and form.is_valid() and components.is_valid():
        with transaction.atomic():
            product = form.save()
            components.instance = product
            components.save()
            refresh_unit_cost(product)
        messages.success(request, "Producto guardado.")
        return redirect("business:products", ws=workspace.pk)
    return render(
        request,
        "business/product_form.html",
        {"workspace": workspace, "form": form, "components": components, "product": product},
        status=400 if request.method == "POST" else 200,
    )


# ---------------------------------------------------------------------------- precios


def _points(fraction: Decimal) -> Decimal:
    """0.3 → 30.00 (para los campos de porcentaje, que aceptan 2 decimales)."""
    return (fraction * HUNDRED).quantize(Decimal("0.01"))


def _fraction(value: Decimal | None) -> Decimal:
    return (value or Decimal("0")) / HUNDRED


def _pricing_context(workspace: Workspace, form: PricingForm) -> dict[str, Any]:
    d = form.cleaned_data
    inputs = PricingInputs(
        unit_cost=d["unit_cost"],
        target_margin=_fraction(d["target_margin"]),
        commission_pct=_fraction(d.get("commission")),
        discount_pct=_fraction(d.get("discount")),
        delivery_cost=d.get("delivery") or Decimal("0"),
        tax_rate=_fraction(d.get("tax")),
        prices_include_tax=d.get("include_tax", False),
        currency=workspace.currency,
    )
    result = compute_price(inputs)
    price = d.get("current_price") or result.net_price
    variable = inputs.total_cost + price * inputs.commission_pct
    return {
        "result": result,
        "price": price,
        "markup_equivalent": result.economics.markup_pct,
        "discount": margin_after_discount(
            price, inputs.total_cost, inputs.discount_pct, inputs.commission_pct
        )
        if inputs.discount_pct
        else None,
        "break_even": break_even_units(d["fixed_costs"], price, variable)
        if d.get("fixed_costs")
        else None,
        "sensitivity": supplier_increase(inputs, price, _fraction(d.get("increase")))
        if d.get("increase")
        else None,
        "capacity": service_capacity(d["labor_minutes"], d["hours"], price, variable)
        if d.get("labor_minutes") and d.get("hours")
        else None,
        "current": unit_economics(
            price, inputs.total_cost, inputs.commission_pct, inputs.discount_pct
        )
        if d.get("current_price")
        else None,
    }


@business_only
@require_http_methods(["GET", "POST"])
def pricing(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    initial: dict[str, Any] = {}
    profile = BusinessProfile.objects.filter(workspace=workspace).first()
    goal = BusinessGoal.objects.filter(workspace=workspace).first()
    if profile:
        initial["tax"] = _points(profile.tax_rate_itbis)
        initial["include_tax"] = profile.prices_include_tax
        initial["hours"] = profile.hours_available_month
    if goal and goal.target_margin_pct is not None:
        initial["target_margin"] = _points(goal.target_margin_pct)
    fixed = sum(
        (
            e.amount * MONTHLY_FACTOR.get(e.frequency, Decimal("1"))
            for e in OperatingExpense.objects.for_workspace(workspace).filter(is_active=True)
        ),
        Decimal("0"),
    )
    if fixed:
        initial["fixed_costs"] = fixed.quantize(Decimal("0.01"))
    product = None
    if request.GET.get("producto"):
        product = _get(Product, workspace, request.GET["producto"])
        inputs = inputs_for_product(product, profile, Decimal("0.30"))
        initial.update(
            unit_cost=inputs.unit_cost,
            commission=_points(inputs.commission_pct),
            current_price=product.price,
            labor_minutes=product.labor_minutes,
        )
    form = PricingForm(request.POST or None, initial=initial)
    context: dict[str, Any] = {"workspace": workspace, "form": form, "product": product}
    if request.method == "POST":
        if form.is_valid():
            context.update(_pricing_context(workspace, form))
        if request.headers.get("HX-Request"):
            return render(request, "business/_pricing_result.html", context)
    elif form.initial:
        bound = PricingForm({**_defaults(PricingForm), **initial})
        if bound.is_valid():
            context.update(_pricing_context(workspace, bound))
    return render(request, "business/pricing.html", context)


def _defaults(form_class: type[PricingForm]) -> dict[str, Any]:
    return {
        name: field.initial
        for name, field in form_class.base_fields.items()
        if field.initial is not None
    }


# ---------------------------------------------------------------------------- deudas


def _debt_page(request: HttpRequest, workspace: Workspace, *, payable: bool) -> HttpResponse:
    model = Payable if payable else Receivable
    form = DebtForm(request.POST or None, workspace=workspace, payable=payable)
    if request.method == "POST" and form.is_valid():
        register = register_payable if payable else register_receivable
        try:
            register(workspace, request.user, form.to_data())
        except ValidationError as exc:
            for message in _errors(exc):
                form.add_error(None, message)
        else:
            messages.success(request, "Registrado.")
            return redirect(
                "business:payables" if payable else "business:receivables", ws=workspace.pk
            )
    debts = model.objects.for_workspace(workspace).select_related(
        "supplier" if payable else "customer"
    )
    open_debts = debts.exclude(status=DebtStatus.PAGADA)
    return render(
        request,
        "business/debts.html",
        {
            "workspace": workspace,
            "payable": payable,
            "form": form,
            "open_debts": open_debts,
            "paid_debts": debts.filter(status=DebtStatus.PAGADA)[:20],
            "total": sum((d.balance for d in open_debts), Decimal("0")),
            "today": timezone.localdate(),
        },
        status=400 if request.method == "POST" else 200,
    )


@business_only
@require_http_methods(["GET", "POST"])
def receivables(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    return _debt_page(request, workspace, payable=False)


@business_only
@require_http_methods(["GET", "POST"])
def payables(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    return _debt_page(request, workspace, payable=True)


def _settle_page(
    request: HttpRequest, workspace: Workspace, debt_id: Any, *, payable: bool
) -> HttpResponse:
    debt = _get(Payable if payable else Receivable, workspace, debt_id)
    form = SettleForm(request.POST or None, workspace=workspace, initial={"amount": debt.balance})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        settle = pay_payable if payable else collect_receivable
        try:
            settle(workspace, request.user, debt, d["amount"], d["account"], d["date"],
                   d["client_uuid"])  # fmt: skip
        except ValidationError as exc:
            for message in _errors(exc):
                form.add_error("amount", message)
        else:
            messages.success(request, "Pago registrado." if payable else "Cobro registrado.")
            return redirect(
                "business:payables" if payable else "business:receivables", ws=workspace.pk
            )
    return render(
        request,
        "business/settle.html",
        {"workspace": workspace, "debt": debt, "form": form, "payable": payable},
        status=400 if request.method == "POST" else 200,
    )


@business_only
@require_http_methods(["GET", "POST"])
def collect(request: HttpRequest, workspace: Workspace, debt_id: Any) -> HttpResponse:
    return _settle_page(request, workspace, debt_id, payable=False)


@business_only
@require_http_methods(["GET", "POST"])
def pay(request: HttpRequest, workspace: Workspace, debt_id: Any) -> HttpResponse:
    return _settle_page(request, workspace, debt_id, payable=True)


# ---------------------------------------------------------------------------- propietario


def _personal(request: HttpRequest) -> Workspace | None:
    return Workspace.objects.filter(owner=request.user, kind=Workspace.Kind.PERSONAL).first()


@business_only
@require_http_methods(["GET", "POST"])
def owner(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    personal = _personal(request)
    if personal is None:
        messages.info(request, "Crea tu espacio personal para mover dinero entre tú y tu negocio.")
        return redirect("workspaces:usage")
    form = OwnerForm(request.POST or None, workspace=workspace, personal=personal)
    today = timezone.localdate()
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        withdrawal = d["kind"] == "retiro_propietario"
        source, target = (workspace, personal) if withdrawal else (personal, workspace)
        accounts = (d["account"], d["personal_account"])
        try:
            transfer_between(
                request.user, source, target, d["amount"], d["date"], d["kind"],
                *(accounts if withdrawal else accounts[::-1]),
                note=d["note"], client_uuid=d["client_uuid"],
            )  # fmt: skip
        except ValidationError as exc:
            for message in _errors(exc):
                form.add_error(None, message)
        else:
            messages.success(request, "Retiro registrado." if withdrawal else "Aporte registrado.")
            return redirect("espacio:dashboard", ws=workspace.pk)
    reserve = load_cash_outlook(workspace, today).reserve
    return render(
        request,
        "business/owner.html",
        {
            "workspace": workspace,
            "form": form,
            "reserve": reserve,
            "message": reserve.message(workspace.currency),
        },
        status=400 if request.method == "POST" else 200,
    )


@business_only
@require_POST
def owner_check(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    """Aviso de reserva operativa mientras se escribe el monto del retiro (htmx)."""
    try:
        amount = Decimal(request.POST.get("amount") or "0")
    except ArithmeticError:
        amount = Decimal("0")
    check = None
    if amount > 0 and request.POST.get("kind", "retiro_propietario") == "retiro_propietario":
        reserve = load_cash_outlook(workspace, timezone.localdate()).reserve
        check = check_withdrawal(reserve, amount, workspace.currency)
    return render(request, "business/_owner_check.html", {"check": check})
