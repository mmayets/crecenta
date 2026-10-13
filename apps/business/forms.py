"""Formularios de las pantallas del negocio (ventas, deudas, propietario, precios, productos)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from django import forms
from django.forms import inlineformset_factory
from django.utils import timezone

from apps.business.models import BusinessProfile, CostComponent, Product, Purchase, Sale
from apps.business.services.purchases import PurchaseData, PurchaseLineData
from apps.business.services.sales import DebtData, SaleData, SaleLineData
from apps.ledger.choices import CategoryGroup
from apps.ledger.models import Account, Category
from apps.workspaces.models import Workspace, WorkspaceTransfer

HUNDRED = Decimal("100")
SALE_ROWS = 3
MONEY = {"max_digits": 14, "decimal_places": 2}


def _date_field(label: str, **kwargs: Any) -> forms.DateField:
    return forms.DateField(
        label=label,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        **kwargs,
    )


def _pct(label: str, **kwargs: Any) -> forms.DecimalField:
    return forms.DecimalField(
        label=label, min_value=0, max_value=99, max_digits=5, decimal_places=2, **kwargs
    )


def _accounts(workspace: Workspace):  # type: ignore[no-untyped-def]
    return Account.objects.for_workspace(workspace).filter(is_archived=False)


class _Base(forms.Form):
    client_uuid = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)

    def __init__(self, *args: Any, workspace: Workspace, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.workspace = workspace
        if "account" in self.fields:
            self.fields["account"].queryset = _accounts(workspace)  # type: ignore[attr-defined]
            self.fields["account"].initial = _accounts(workspace).first()


class SaleForm(_Base):
    date = _date_field("Fecha", initial=timezone.localdate)
    payment = forms.ChoiceField(
        label="Forma de pago",
        choices=Sale.Payment.choices,
        initial=Sale.Payment.CONTADO,
        widget=forms.RadioSelect,
    )
    account = forms.ModelChoiceField(
        label="¿Dónde entró el dinero?", queryset=Account.objects.none(), required=False
    )
    customer_name = forms.CharField(label="Cliente (opcional)", max_length=120, required=False)
    due_date = _date_field("¿Cuándo te pagará? (crédito)", required=False)
    apply_tax = forms.BooleanField(label="Cobrar ITBIS en esta venta", required=False)
    note = forms.CharField(label="Nota (opcional)", max_length=140, required=False)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        products = Product.objects.for_workspace(self.workspace).filter(is_active=True)
        self.rows = []
        for i in range(1, SALE_ROWS + 1):
            self.fields[f"producto_{i}"] = forms.ModelChoiceField(
                label="Producto", queryset=products, required=i == 1, empty_label="—"
            )
            self.fields[f"cantidad_{i}"] = forms.DecimalField(
                label="Cantidad", min_value=Decimal("0.01"), max_digits=10, decimal_places=2,
                required=False, initial=1 if i == 1 else None,
            )  # fmt: skip
            self.fields[f"precio_{i}"] = forms.DecimalField(
                label="Precio (vacío = el del producto)", min_value=0, required=False, **MONEY
            )
            self.fields[f"descuento_{i}"] = _pct("Descuento %", required=False)
            self.rows.append(
                [self[f"{n}_{i}"] for n in ("producto", "cantidad", "precio", "descuento")]
            )
        profile = BusinessProfile.objects.filter(workspace=self.workspace).first()
        self.charges_tax = bool(profile and profile.tax_rate_itbis > 0)
        if self.charges_tax:
            self.fields["apply_tax"].initial = True
        else:
            del self.fields["apply_tax"]

    def clean(self) -> dict[str, Any]:
        data = super().clean()
        if data.get("payment") == Sale.Payment.CONTADO and not data.get("account"):
            self.add_error("account", "Indica en qué cuenta entró el dinero.")
        for i in range(1, SALE_ROWS + 1):
            if data.get(f"producto_{i}") and not data.get(f"cantidad_{i}"):
                self.add_error(f"cantidad_{i}", "Indica la cantidad.")
        return data

    def to_sale_data(self) -> SaleData:
        d = self.cleaned_data
        lines = [
            SaleLineData(
                product=d[f"producto_{i}"],
                qty=d[f"cantidad_{i}"],
                unit_price=d.get(f"precio_{i}"),
                discount_pct=(d.get(f"descuento_{i}") or Decimal("0")) / HUNDRED,
            )
            for i in range(1, SALE_ROWS + 1)
            if d.get(f"producto_{i}")
        ]
        credit = d["payment"] == Sale.Payment.CREDITO
        return SaleData(
            date=d["date"],
            lines=lines,
            payment=d["payment"],
            account=None if credit else d["account"],
            customer_name=d["customer_name"],
            due_date=d.get("due_date") if credit else None,
            apply_tax=d.get("apply_tax", False),
            note=d["note"],
            client_uuid=d["client_uuid"],
        )


class DebtForm(_Base):
    concept = forms.CharField(label="Concepto", max_length=140)
    amount = forms.DecimalField(label="Monto", min_value=Decimal("0.01"), **MONEY)
    counterpart_name = forms.CharField(max_length=120, required=False)
    due_date = _date_field("Vence", required=False)
    category = forms.ModelChoiceField(
        label="Categoría", queryset=Category.objects.none(), required=False
    )

    def __init__(self, *args: Any, payable: bool, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["counterpart_name"].label = "Proveedor" if payable else "Cliente"
        if payable:
            self.fields["category"].queryset = Category.objects.for_workspace(  # type: ignore[attr-defined]
                self.workspace
            ).filter(
                group__in=[CategoryGroup.COSTO_VARIABLE, CategoryGroup.GASTO_OPERATIVO],
                is_archived=False,
            )
        else:
            del self.fields["category"]

    def to_data(self) -> DebtData:
        d = self.cleaned_data
        return DebtData(
            concept=d["concept"],
            amount=d["amount"],
            due_date=d.get("due_date"),
            counterpart_name=d["counterpart_name"],
            category=d.get("category"),
            client_uuid=d["client_uuid"],
        )


class SettleForm(_Base):
    amount = forms.DecimalField(label="Monto", min_value=Decimal("0.01"), **MONEY)
    account = forms.ModelChoiceField(label="Cuenta", queryset=Account.objects.none())
    date = _date_field("Fecha", initial=timezone.localdate)


class OwnerForm(_Base):
    kind = forms.ChoiceField(
        label="¿Qué quieres hacer?",
        choices=[
            (WorkspaceTransfer.Kind.RETIRO_PROPIETARIO, "Retirar dinero para mí"),
            (WorkspaceTransfer.Kind.APORTE, "Poner dinero en el negocio"),
        ],
        widget=forms.RadioSelect,
        initial=WorkspaceTransfer.Kind.RETIRO_PROPIETARIO,
    )
    amount = forms.DecimalField(label="Monto", min_value=Decimal("0.01"), **MONEY)
    account = forms.ModelChoiceField(label="Cuenta del negocio", queryset=Account.objects.none())
    personal_account = forms.ModelChoiceField(
        label="Tu cuenta personal", queryset=Account.objects.none()
    )
    date = _date_field("Fecha", initial=timezone.localdate)
    note = forms.CharField(label="Nota (opcional)", max_length=140, required=False)

    def __init__(self, *args: Any, personal: Workspace, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.personal = personal
        self.fields["personal_account"].queryset = _accounts(personal)  # type: ignore[attr-defined]
        self.fields["personal_account"].initial = _accounts(personal).first()


class PricingForm(forms.Form):
    unit_cost = forms.DecimalField(label="Costo por unidad", min_value=0, initial=600, **MONEY)
    target_margin = _pct("Margen que quieres (%)", initial=30)
    commission = _pct("Comisión de venta (%)", initial=0, required=False)
    discount = _pct("Descuento habitual (%)", initial=0, required=False)
    delivery = forms.DecimalField(
        label="Entrega por unidad", min_value=0, initial=0, required=False, **MONEY
    )
    tax = _pct("ITBIS (%)", initial=0, required=False)
    include_tax = forms.BooleanField(label="Publico precios con ITBIS", required=False)
    current_price = forms.DecimalField(
        label="Precio actual (opcional)", min_value=0, required=False, **MONEY
    )
    fixed_costs = forms.DecimalField(
        label="Gastos fijos del mes (para el equilibrio)", min_value=0, required=False, **MONEY
    )
    increase = _pct("Si el proveedor sube (%)", initial=10, required=False)
    labor_minutes = forms.IntegerField(
        label="Minutos por servicio (opcional)", min_value=1, required=False
    )
    hours = forms.IntegerField(label="Horas disponibles al mes", min_value=1, required=False)

    def clean(self) -> dict[str, Any]:
        data = super().clean()
        margin = data.get("target_margin") or Decimal("0")
        if margin + (data.get("commission") or Decimal("0")) >= 100:
            self.add_error("target_margin", "El margen más la comisión debe ser menor que 100 %.")
        return data


ComponentFormSet = inlineformset_factory(
    Product,
    CostComponent,
    fields=["name", "type", "amount"],
    labels={"name": "Componente", "type": "Tipo", "amount": "Monto (o 0.10 = 10 % si es comisión)"},
    extra=2,
    can_delete=True,
)


# ---------------------------------------------------------------------------- Fase 3

PURCHASE_ROWS = 3


class PurchaseForm(_Base):
    date = _date_field("Fecha de la factura", initial=timezone.localdate)
    supplier_name = forms.CharField(label="Proveedor (opcional)", max_length=120, required=False)
    payment = forms.ChoiceField(
        label="Forma de pago",
        choices=Purchase.Payment.choices,
        initial=Purchase.Payment.CONTADO,
        widget=forms.RadioSelect,
    )
    account = forms.ModelChoiceField(
        label="¿De dónde salió el dinero?", queryset=Account.objects.none(), required=False
    )
    due_date = _date_field("¿Cuándo le pagas? (crédito)", required=False)
    tax = forms.DecimalField(
        label="ITBIS de la factura (opcional)", min_value=0, required=False, **MONEY
    )
    note = forms.CharField(label="Nota (opcional)", max_length=140, required=False)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        products = Product.objects.for_workspace(self.workspace).filter(
            tracks_inventory=True, is_active=True
        )
        self.rows = []
        for i in range(1, PURCHASE_ROWS + 1):
            self.fields[f"producto_{i}"] = forms.ModelChoiceField(
                label="Producto", queryset=products, required=i == 1, empty_label="—"
            )
            self.fields[f"cantidad_{i}"] = forms.DecimalField(
                label="Cantidad", min_value=Decimal("0.001"), max_digits=12, decimal_places=3,
                required=False,
            )  # fmt: skip
            self.fields[f"costo_{i}"] = forms.DecimalField(
                label="Costo por unidad (sin ITBIS)", min_value=0, max_digits=14,
                decimal_places=4, required=False,
            )  # fmt: skip
            self.rows.append([self[f"{n}_{i}"] for n in ("producto", "cantidad", "costo")])

    def clean(self) -> dict[str, Any]:
        data = super().clean()
        if data.get("payment") == Purchase.Payment.CONTADO and not data.get("account"):
            self.add_error("account", "Indica de qué cuenta salió el dinero.")
        for i in range(1, PURCHASE_ROWS + 1):
            if data.get(f"producto_{i}"):
                if not data.get(f"cantidad_{i}"):
                    self.add_error(f"cantidad_{i}", "Indica la cantidad.")
                if data.get(f"costo_{i}") is None:
                    self.add_error(f"costo_{i}", "Indica el costo por unidad.")
        return data

    def to_purchase_data(self) -> PurchaseData:
        d = self.cleaned_data
        credit = d["payment"] == Purchase.Payment.CREDITO
        return PurchaseData(
            date=d["date"],
            lines=[
                PurchaseLineData(d[f"producto_{i}"], d[f"cantidad_{i}"], d[f"costo_{i}"])
                for i in range(1, PURCHASE_ROWS + 1)
                if d.get(f"producto_{i}")
            ],
            payment=d["payment"],
            account=None if credit else d["account"],
            supplier_name=d["supplier_name"],
            tax=d.get("tax") or Decimal("0"),
            due_date=d.get("due_date") if credit else None,
            note=d["note"],
            client_uuid=d["client_uuid"],
        )


class StockActionForm(forms.Form):
    ACTIONS = [
        ("contar", "Conté las unidades que tengo"),
        ("merma", "Se perdieron o dañaron unidades"),
        ("inicial", "Registrar lo que ya tenía (inventario inicial)"),
    ]
    client_uuid = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)
    action = forms.ChoiceField(label="¿Qué pasó?", choices=ACTIONS, widget=forms.RadioSelect,
                               initial="contar")  # fmt: skip
    qty = forms.DecimalField(
        label="Unidades", min_value=0, max_digits=12, decimal_places=3,
        help_text="Contar: cuántas tienes ahora. Merma: cuántas se perdieron.",
    )  # fmt: skip
    unit_cost = forms.DecimalField(
        label="Costo por unidad (solo inventario inicial)", min_value=0, max_digits=14,
        decimal_places=4, required=False,
    )  # fmt: skip
    date = _date_field("Fecha", initial=timezone.localdate)
    note = forms.CharField(label="Nota (opcional)", max_length=140, required=False)

    def clean(self) -> dict[str, Any]:
        data = super().clean()
        if data.get("action") == "inicial" and data.get("unit_cost") is None:
            self.add_error("unit_cost", "Indica cuánto te costó cada unidad.")
        return data
