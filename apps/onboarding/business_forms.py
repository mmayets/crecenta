"""Formularios del onboarding de negocio. Sirven para el paso a paso (editan lo guardado) y para la
confirmación del modo conversacional (precargados con lo extraído; nada se guarda sin confirmar)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django import forms

from apps.business.models import BusinessGoal, BusinessProfile, OperatingExpense, Product
from apps.ledger.choices import CategoryGroup
from apps.workspaces.models import Workspace

from .forms import AccountForm, WorkspaceModelForm, _categories

HUNDRED = Decimal("100")
DEFAULT_TAX_PCT = Decimal("18")


def _pct_field(label: str, **kwargs: Any) -> forms.DecimalField:
    return forms.DecimalField(
        label=label, min_value=0, max_value=95, max_digits=5, decimal_places=2, **kwargs
    )


class ProfileForm(forms.Form):
    activity = forms.CharField(
        label="¿A qué se dedica?",
        max_length=120,
        widget=forms.TextInput(attrs={"placeholder": "Ej.: repostería, salón de belleza, colmado"}),
    )
    model = forms.ChoiceField(label="Vendes", choices=BusinessProfile.Model.choices)
    cobra_itbis = forms.BooleanField(label="Cobro ITBIS en mis ventas", required=False)
    tasa_pct = _pct_field("Tasa del impuesto (%)", initial=DEFAULT_TAX_PCT, required=False)
    prices_include_tax = forms.BooleanField(
        label="Mis precios ya incluyen el impuesto", required=False
    )
    hours_available_month = forms.IntegerField(
        label="Horas que puedes trabajar al mes (si vendes servicios)",
        min_value=1,
        max_value=744,
        required=False,
    )

    def __init__(self, *args: Any, workspace: Workspace, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.workspace = workspace
        profile = BusinessProfile.objects.filter(workspace=workspace).first()
        if profile and not self.initial:
            self.initial = {
                "activity": profile.activity,
                "model": profile.model,
                "cobra_itbis": profile.tax_rate_itbis > 0,
                "tasa_pct": (profile.tax_rate_itbis * HUNDRED) or DEFAULT_TAX_PCT,
                "prices_include_tax": profile.prices_include_tax,
                "hours_available_month": profile.hours_available_month,
            }

    def save(self) -> BusinessProfile:
        data = self.cleaned_data
        rate = (data.get("tasa_pct") or DEFAULT_TAX_PCT) / HUNDRED if data["cobra_itbis"] else 0
        profile, _ = BusinessProfile.objects.update_or_create(
            workspace=self.workspace,
            defaults={
                "activity": data["activity"],
                "model": data["model"],
                "tax_rate_itbis": rate,
                "prices_include_tax": data["cobra_itbis"] and data["prices_include_tax"],
                "hours_available_month": data.get("hours_available_month"),
            },
        )
        return profile


class ProductForm(WorkspaceModelForm):
    class Meta:
        model = Product
        fields = [
            "name", "price", "unit_cost", "expected_monthly_units", "is_service", "labor_minutes",
            "tracks_inventory", "stock_minimum", "is_supply",
        ]  # fmt: skip
        labels = {
            "name": "Producto o servicio",
            "price": "Precio de venta (sin ITBIS)",
            "unit_cost": "¿Cuánto te cuesta cada uno?",
            "expected_monthly_units": "¿Cuántos esperas vender al mes?",
            "is_service": "Es un servicio",
            "labor_minutes": "Minutos que te toma (servicios)",
            "tracks_inventory": "Lo compro hecho y quiero controlar su inventario",
            "stock_minimum": "Avísame cuando queden (unidades)",
            "is_supply": "Es un insumo (lo uso para elaborar, no lo vendo)",
        }
        help_texts = {
            "unit_cost": "Materiales, empaque, entrega y comisiones de una unidad.",
            "tracks_inventory": "Para mercancía que compras y revendes: el costo de lo vendido "
            "será el costo promedio de tus compras.",
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["stock_minimum"].required = False
        if self.instance._state.adding:  # el id (UUID) existe aunque no esté guardado
            # Sin valor inicial: una fila vacía del formset no cuenta como "cambiada".
            self.fields["stock_minimum"].initial = None
            self.initial.pop("stock_minimum", None)

    def clean(self) -> dict[str, Any]:
        data = super().clean()
        if data.get("is_supply") and not data.get("tracks_inventory"):
            self.add_error("tracks_inventory", "Un insumo necesita control de inventario.")
        return data

    def clean_stock_minimum(self) -> Decimal:
        return self.cleaned_data.get("stock_minimum") or Decimal("0")

    def clean_name(self) -> str:
        name = " ".join(self.cleaned_data["name"].split())
        duplicate = (
            Product.objects.for_workspace(self.workspace)
            .filter(name__iexact=name)
            .exclude(pk=self.instance.pk)
            .exists()
        )
        if duplicate:
            raise forms.ValidationError("Ya tienes un producto con ese nombre.")
        return name


class ExpenseForm(WorkspaceModelForm):
    class Meta:
        model = OperatingExpense
        fields = ["name", "category", "amount", "frequency", "due_day", "is_reducible"]
        labels = {
            "name": "Gasto",
            "amount": "Monto",
            "due_day": "Día en que lo pagas",
            "is_reducible": "Lo podría reducir",
        }
        help_texts = {"due_day": "Si es semanal: 1 = lunes … 7 = domingo."}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = _categories(
            self.workspace, CategoryGroup.GASTO_OPERATIVO
        )


class BusinessAccountForm(AccountForm):
    class Meta(AccountForm.Meta):
        labels = {"opening_balance": "¿Cuánto tiene hoy?", "is_savings": "Es un ahorro del negocio"}


class GoalForm(forms.Form):
    margen_pct = _pct_field(
        "¿Qué porcentaje de cada venta quieres que te quede? (margen)", required=False
    )
    target_profit = forms.DecimalField(
        label="Ganancia que quieres al mes", min_value=0, max_digits=14, decimal_places=2,
        required=False,
    )  # fmt: skip
    cash_reserve = forms.DecimalField(
        label="Dinero que siempre quieres tener en caja", min_value=0, max_digits=14,
        decimal_places=2, required=False,
    )  # fmt: skip
    planned_owner_draw = forms.DecimalField(
        label="¿Cuánto quieres retirar al mes para ti?", min_value=0, max_digits=14,
        decimal_places=2, required=False,
    )  # fmt: skip

    def __init__(self, *args: Any, workspace: Workspace, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.workspace = workspace
        goal = BusinessGoal.objects.filter(workspace=workspace).first()
        if goal and not self.initial:
            self.initial = {
                "margen_pct": (
                    goal.target_margin_pct * HUNDRED if goal.target_margin_pct is not None else None
                ),
                "target_profit": goal.target_profit,
                "cash_reserve": goal.cash_reserve,
                "planned_owner_draw": goal.planned_owner_draw,
            }

    def save(self) -> BusinessGoal:
        data = self.cleaned_data
        margin = data.get("margen_pct")
        goal, _ = BusinessGoal.objects.update_or_create(
            workspace=self.workspace,
            defaults={
                "target_margin_pct": margin / HUNDRED if margin is not None else None,
                "target_profit": data.get("target_profit"),
                "cash_reserve": data.get("cash_reserve") or 0,
                "planned_owner_draw": data.get("planned_owner_draw") or 0,
            },
        )
        return goal


BUSINESS_SECTION_FORMS: dict[str, type[WorkspaceModelForm]] = {
    "productos": ProductForm,
    "gastos": ExpenseForm,
    "efectivo": BusinessAccountForm,
}
BUSINESS_SINGLE_FORMS: dict[str, type[forms.Form]] = {
    "perfil": ProfileForm,
    "objetivos": GoalForm,
}


class BusinessConversationForm(forms.Form):
    texto = forms.CharField(
        label="Cuéntanos de tu negocio con tus palabras",
        max_length=4000,
        widget=forms.Textarea(
            attrs={
                "rows": 6,
                "placeholder": (
                    "Ej.: Hago bizcochos por encargo. Cada uno lo vendo a 857 y me cuesta como "
                    "600 en materiales. Vendo unos 40 al mes. Pago 8 mil de alquiler el día 5. "
                    "Tengo 15 mil en caja y quiero sacar 10 mil al mes para mí."
                ),
            }
        ),
    )
