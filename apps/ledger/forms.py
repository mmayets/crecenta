import uuid
from datetime import date

from django import forms
from django.utils import timezone

from apps.ledger.choices import BUSINESS_GROUPS, PERSONAL_GROUPS, CategoryGroup, TxKind
from apps.ledger.models import Account, Category
from apps.workspaces.models import Workspace

QUICK_KINDS = [
    (TxKind.GASTO, "Gasto"),
    (TxKind.INGRESO, "Ingreso"),
    (TxKind.PAGO_DEUDA, "Cuota"),
]
# En el negocio las ventas se registran desde Ventas (con productos y costo).
BUSINESS_QUICK_KINDS = [
    (TxKind.GASTO, "Gasto"),
    (TxKind.COMPRA_INVENTARIO, "Compra de materiales"),
    (TxKind.INGRESO, "Otro ingreso"),
    (TxKind.PAGO_DEUDA, "Cuota de préstamo"),
]


def _today() -> date:
    return timezone.localdate()


class _WorkspaceForm(forms.Form):
    def __init__(self, *args, workspace: Workspace, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.workspace = workspace
        accounts = Account.objects.for_workspace(workspace).filter(is_archived=False)
        for name in ("account", "from_account", "to_account"):
            if name in self.fields:
                self.fields[name].queryset = accounts

    def highlight(self, names) -> None:
        for name in names:
            if name in self.fields:
                self.fields[name].widget.attrs.update({"class": "dudoso"})


class QuickEntryForm(_WorkspaceForm):
    """Formulario rápido: monto, categoría y cuenta (el resto tiene valores por defecto)."""

    kind = forms.ChoiceField(
        label="Tipo", choices=QUICK_KINDS, initial=TxKind.GASTO, widget=forms.RadioSelect
    )
    amount = forms.DecimalField(
        label="Monto",
        min_value=0.01,
        max_digits=14,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"inputmode": "decimal", "autofocus": True, "step": "0.01"}),
    )
    category = forms.ModelChoiceField(
        label="Categoría",
        queryset=Category.objects.none(),
        required=False,
        empty_label="Sin categoría",
    )
    account = forms.ModelChoiceField(
        label="Cuenta", queryset=Account.objects.none(), empty_label=None
    )
    date = forms.DateField(
        label="Fecha",
        initial=_today,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    description = forms.CharField(label="Nota (opcional)", max_length=140, required=False)
    client_uuid = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)
    source = forms.ChoiceField(
        choices=[("manual", "manual"), ("texto", "texto"), ("voz", "voz")],
        widget=forms.HiddenInput,
        initial="manual",
    )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if self.workspace.is_business:
            self.fields["kind"].choices = BUSINESS_QUICK_KINDS
        self.fields["category"].queryset = (
            Category.objects.for_workspace(self.workspace)
            .filter(is_archived=False)
            .order_by("group", "name")
        )
        self.fields["category"].label_from_instance = lambda c: (
            f"{c.name} · {CategoryGroup(c.group).label}"
        )
        self.fields["account"].initial = self.fields["account"].queryset.first()

    def as_sync_payload(self) -> dict:
        data = self.cleaned_data
        return {
            "client_uuid": str(data["client_uuid"]),
            "account_id": str(data["account"].pk),
            "date": data["date"].isoformat(),
            "amount": str(data["amount"]),
            "kind": data["kind"],
            "category_id": str(data["category"].pk) if data["category"] else "",
            "description": data["description"],
            "source": data["source"],
        }


class TransferForm(_WorkspaceForm):
    kind = forms.ChoiceField(
        label="Tipo",
        choices=[
            (TxKind.TRANSFERENCIA_INTERNA, "Entre mis cuentas"),
            (TxKind.RETIRO_EFECTIVO, "Retiro de efectivo"),
        ],
        widget=forms.RadioSelect,
        initial=TxKind.TRANSFERENCIA_INTERNA,
    )
    from_account = forms.ModelChoiceField(label="Desde", queryset=Account.objects.none())
    to_account = forms.ModelChoiceField(label="Hacia", queryset=Account.objects.none())
    amount = forms.DecimalField(label="Monto", min_value=0.01, max_digits=14, decimal_places=2)
    date = forms.DateField(
        label="Fecha",
        initial=_today,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    is_saving = forms.BooleanField(label="Es un aporte a mi ahorro", required=False)
    client_uuid = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)

    def clean(self):
        data = super().clean()
        if data.get("from_account") and data.get("from_account") == data.get("to_account"):
            self.add_error("to_account", "Elige una cuenta distinta.")
        return data

    def as_sync_payload(self) -> dict:
        data = self.cleaned_data
        saving = None
        if data["is_saving"]:
            saving = (
                Category.objects.for_workspace(self.workspace)
                .filter(group=CategoryGroup.AHORRO)
                .first()
            )
        return {
            "client_uuid": str(data["client_uuid"]),
            "account_id": str(data["from_account"].pk),
            "to_account_id": str(data["to_account"].pk),
            "date": data["date"].isoformat(),
            "amount": str(data["amount"]),
            "kind": data["kind"],
            "category_id": str(saving.pk) if saving else "",
            "source": "manual",
        }


class FreeTextForm(forms.Form):
    texto = forms.CharField(
        label="Escribe o dicta el movimiento",
        max_length=500,
        widget=forms.TextInput(attrs={"placeholder": "Ej.: gasté 350 en el colmado ayer"}),
    )
    via = forms.ChoiceField(
        choices=[("texto", "texto"), ("voz", "voz")], required=False, widget=forms.HiddenInput
    )


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "group"]
        labels = {"name": "Nombre", "group": "Grupo"}

    def __init__(self, *args, workspace: Workspace, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.instance.workspace = workspace
        allowed = PERSONAL_GROUPS if workspace.is_personal else BUSINESS_GROUPS
        self.fields["group"].choices = [c for c in CategoryGroup.choices if c[0] in allowed]
