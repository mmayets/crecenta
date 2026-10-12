"""Formularios del onboarding personal.

Los mismos formularios sirven para el wizard (editan lo ya guardado) y para la tabla de
confirmación del modo conversacional (se precargan con lo extraído por la IA y nada se guarda hasta
que la persona confirma).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django import forms
from django.forms import BaseModelFormSet, modelformset_factory

from apps.core.periods import Frequency
from apps.ledger.choices import CategoryGroup
from apps.ledger.models import Account, Category
from apps.personal.models import (
    Commitment,
    Debt,
    EssentialEstimate,
    IncomeSource,
    PersonalProfile,
    Preference,
    SavingsGoal,
)
from apps.personal.services.types import Priority
from apps.receipts.services.ingest import normalize
from apps.workspaces.models import Workspace

WEEKDAYS = [
    (0, "Lunes"), (1, "Martes"), (2, "Miércoles"), (3, "Jueves"),
    (4, "Viernes"), (5, "Sábado"), (6, "Domingo"),
]  # fmt: skip
DAY = {"min_value": 1, "max_value": 31, "required": False}


def _categories(workspace: Workspace, *groups: str):
    return Category.objects.for_workspace(workspace).filter(group__in=groups, is_archived=False)


class WorkspaceModelForm(forms.ModelForm):
    """ModelForm ligado a un espacio: el espacio se asigna antes de validar el modelo."""

    def __init__(self, *args: Any, workspace: Workspace, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.workspace = workspace
        self.instance.workspace = workspace


class IncomeForm(WorkspaceModelForm):
    dia_1 = forms.IntegerField(label="Día de cobro", **DAY)
    dia_2 = forms.IntegerField(label="Segundo día de cobro (quincenal)", **DAY)
    dia_semana = forms.TypedChoiceField(
        label="Día de cobro (semanal)",
        choices=[("", "—"), *WEEKDAYS],
        coerce=int,
        required=False,
        empty_value=None,
    )

    class Meta:
        model = IncomeSource
        fields = ["name", "net_amount", "frequency"]
        labels = {"name": "¿De dónde viene?", "net_amount": "Monto neto de cada cobro"}
        help_texts = {"net_amount": "Si cobras quincenal, escribe lo que recibes cada quincena."}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        days = list(self.instance.pay_days or [])
        if self.instance.frequency == Frequency.SEMANAL and days:
            self.fields["dia_semana"].initial = days[0]
        elif days:
            self.fields["dia_1"].initial = days[0]
            if len(days) > 1:
                self.fields["dia_2"].initial = days[1]

    def clean(self) -> dict[str, Any]:
        data = super().clean()
        frequency = data.get("frequency")
        if frequency == Frequency.SEMANAL:
            days = [] if data.get("dia_semana") is None else [data["dia_semana"]]
            if not days:
                self.add_error("dia_semana", "Indica qué día de la semana cobras.")
        else:
            days = [d for d in (data.get("dia_1"), data.get("dia_2")) if d]
            if frequency == Frequency.MENSUAL and len(days) != 1:
                self.add_error("dia_1", "Indica el día del mes en que cobras.")
            if frequency == Frequency.QUINCENAL and len(days) != 2:
                self.add_error("dia_2", "Indica los dos días de cobro (por ejemplo 15 y 30).")
        self.instance.pay_days = days
        return data

    def _update_errors(self, errors: Any) -> None:
        # La validación del modelo reporta los días como `pay_days`, que no es un campo visible:
        # se muestra en el campo de día (si este formulario no explicó ya el problema).
        error_dict = getattr(errors, "error_dict", None)
        if error_dict and "pay_days" in error_dict:
            messages = error_dict.pop("pay_days")
            day_fields = ("dia_1", "dia_2", "dia_semana", "net_amount")
            if not any(name in self._errors for name in day_fields):
                target = (
                    "dia_semana"
                    if self.data.get(self.add_prefix("frequency")) == "semanal"
                    else "dia_1"
                )
                error_dict.setdefault(target, []).extend(messages)
        super()._update_errors(errors)


class AccountForm(WorkspaceModelForm):
    class Meta:
        model = Account
        fields = ["name", "type", "opening_balance", "is_savings"]
        labels = {"opening_balance": "¿Cuánto tienes hoy?", "is_savings": "Es para ahorrar"}

    def __init__(self, *args: Any, merge_existing: bool = False, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.instance.currency = self.workspace.currency
        if merge_existing and self.instance._state.adding:
            # Conversacional: "tengo 2 mil en efectivo" actualiza la cuenta Efectivo existente.
            name = normalize(self.initial.get("name"))
            existing = next(
                (
                    a
                    for a in Account.objects.for_workspace(self.workspace)
                    if normalize(a.name) == name
                ),
                None,
            )
            if existing is not None:
                self.instance = existing


class CommitmentForm(WorkspaceModelForm):
    class Meta:
        model = Commitment
        fields = ["name", "category", "amount", "frequency", "due_day", "is_fixed"]
        labels = {
            "name": "Pago",
            "amount": "Monto",
            "due_day": "Día en que vence",
            "is_fixed": "Siempre es el mismo monto",
        }
        help_texts = {"due_day": "Para avisarte antes de cada pago."}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = _categories(
            self.workspace,
            CategoryGroup.COMPROMISO_FIJO,
            CategoryGroup.ESENCIAL_VARIABLE,
            CategoryGroup.DISCRECIONAL,
        )


class DebtForm(WorkspaceModelForm):
    class Meta:
        model = Debt
        fields = ["name", "installment", "balance", "due_day", "interest_rate", "end_date"]
        labels = {"name": "Préstamo o tarjeta", "balance": "Lo que debes hoy"}
        widgets = {"end_date": forms.DateInput(attrs={"type": "date"})}


class SavingsGoalForm(WorkspaceModelForm):
    selected_weekdays = forms.TypedMultipleChoiceField(
        label="Días en que ahorras",
        choices=WEEKDAYS,
        coerce=int,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = SavingsGoal
        fields = [
            "purpose", "target_amount", "contribution_amount", "contribution_frequency",
            "daily_mode", "selected_weekdays", "deadline",
        ]  # fmt: skip
        labels = {
            "purpose": "¿Para qué ahorras?",
            "target_amount": "¿Cuánto quieres juntar? (opcional)",
            "contribution_amount": "¿Cuánto apartarás cada vez?",
            "deadline": "¿Para cuándo? (opcional)",
        }
        widgets = {"deadline": forms.DateInput(attrs={"type": "date"})}


class WorkspaceFormSet(BaseModelFormSet):
    def __init__(
        self, *args: Any, workspace: Workspace, form_kwargs: dict | None = None, **kwargs: Any
    ) -> None:
        self.workspace = workspace
        kwargs.setdefault("queryset", self.model.objects.for_workspace(workspace))
        super().__init__(
            *args, form_kwargs={**(form_kwargs or {}), "workspace": workspace}, **kwargs
        )


def formset_class(form: type[WorkspaceModelForm], extra: int = 1):
    return modelformset_factory(
        form._meta.model, form=form, formset=WorkspaceFormSet, extra=extra, can_delete=True
    )


SECTION_FORMS: dict[str, type[WorkspaceModelForm]] = {
    "ingresos": IncomeForm,
    "cuentas": AccountForm,
    "compromisos": CommitmentForm,
    "deudas": DebtForm,
    "ahorro": SavingsGoalForm,
}


class EssentialsForm(forms.Form):
    """Un monto por cada categoría de gasto esencial variable."""

    def __init__(self, *args: Any, workspace: Workspace, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.workspace = workspace
        estimates = {
            e.category_id: e.amount for e in EssentialEstimate.objects.for_workspace(workspace)
        }
        self.categories = list(_categories(workspace, CategoryGroup.ESENCIAL_VARIABLE))
        for category in self.categories:
            self.fields[f"cat_{category.pk}"] = forms.DecimalField(
                label=category.name,
                min_value=0,
                max_digits=14,
                decimal_places=2,
                required=False,
                initial=estimates.get(category.pk),
            )

    def save(self) -> int:
        saved = 0
        for category in self.categories:
            amount = self.cleaned_data.get(f"cat_{category.pk}")
            if amount:
                EssentialEstimate.objects.update_or_create(
                    workspace=self.workspace, category=category, defaults={"amount": amount}
                )
                saved += 1
            else:
                EssentialEstimate.objects.for_workspace(self.workspace).filter(
                    category=category
                ).delete()
        return saved


class PreferencesForm(forms.Form):
    ocio_deseado = forms.DecimalField(
        label="¿Cuánto te gustaría tener para ocio en cada período? (opcional)",
        min_value=0,
        max_digits=14,
        decimal_places=2,
        required=False,
    )
    reserva_pct = forms.DecimalField(
        label="Reserva para imprevistos (% de tus gastos esenciales)",
        min_value=0,
        max_value=50,
        max_digits=5,
        decimal_places=2,
        initial=Decimal("10"),
    )

    CHOICES = [
        ("", "Sin preferencia"),
        (Priority.PRIORITARIO, "Prioritario"),
        (Priority.REDUCIBLE, "Lo podría reducir"),
    ]

    def __init__(self, *args: Any, workspace: Workspace, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.workspace = workspace
        profile = PersonalProfile.objects.filter(workspace=workspace).first()
        if profile:
            self.fields["ocio_deseado"].initial = profile.discretionary_wish
            self.fields["reserva_pct"].initial = profile.reserve_pct * 100
        current = {p.category_id: p.priority for p in Preference.objects.for_workspace(workspace)}
        self.categories = list(
            _categories(
                workspace,
                CategoryGroup.ESENCIAL_VARIABLE,
                CategoryGroup.DISCRECIONAL,
                CategoryGroup.AHORRO,
            )
        )
        for category in self.categories:
            self.fields[f"pref_{category.pk}"] = forms.ChoiceField(
                label=category.name,
                choices=self.CHOICES,
                required=False,
                initial=current.get(category.pk, ""),
            )

    def save(self) -> None:
        PersonalProfile.objects.update_or_create(
            workspace=self.workspace,
            defaults={
                "discretionary_wish": self.cleaned_data["ocio_deseado"],
                "reserve_pct": self.cleaned_data["reserva_pct"] / 100,
            },
        )
        for category in self.categories:
            value = self.cleaned_data.get(f"pref_{category.pk}")
            if value:
                Preference.objects.update_or_create(
                    workspace=self.workspace, category=category, defaults={"priority": value}
                )
            else:
                Preference.objects.for_workspace(self.workspace).filter(category=category).delete()


class ConversationForm(forms.Form):
    texto = forms.CharField(
        label="Cuéntanos tu situación con tus palabras",
        max_length=4000,
        widget=forms.Textarea(
            attrs={
                "rows": 6,
                "placeholder": (
                    "Ej.: Cobro 50 mil al mes el día 30. Pago 18 mil de alquiler el 5, la luz "
                    "unos 2,500 el 15. En comida gasto como 12 mil. Quiero ahorrar 5 mil al mes "
                    "para un fondo de emergencia."
                ),
            }
        ),
    )
