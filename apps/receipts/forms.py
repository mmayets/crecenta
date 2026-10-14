from datetime import date

from django import forms

from apps.ledger.choices import CategoryGroup, Rubro
from apps.ledger.models import Account, Category
from apps.receipts.models import Receipt
from apps.receipts.services.ocr import doubtful_fields
from apps.receipts.services.review import suggested_account, suggested_category


class UploadForm(forms.Form):
    file = forms.FileField(
        label="Foto o PDF del comprobante",
        widget=forms.ClearableFileInput(
            # x-ref/@change: al elegir una foto, el navegador busca su código QR (fotoConQR).
            attrs={"accept": "image/*,application/pdf", "capture": "environment",
                   "x-ref": "archivo", "@change": "revisar"}
        ),
    )  # fmt: skip


# Campo del formulario ← campo leído por la IA
FIELD_SOURCES = {
    "description": "comercio",
    "date": "fecha",
    "amount": "total",
    "category": "categoria_propuesta",
    "account": "medio_pago",
}


class ReviewForm(forms.Form):
    description = forms.CharField(label="Comercio o descripción", max_length=140)
    date = forms.DateField(
        label="Fecha", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
    )
    amount = forms.DecimalField(label="Total", min_value=0.01, max_digits=14, decimal_places=2)
    category = forms.ModelChoiceField(
        label="Categoría", queryset=Category.objects.none(), required=False
    )
    account = forms.ModelChoiceField(label="Pagado desde", queryset=Account.objects.none())
    rubro = forms.ChoiceField(
        label="Rubro del gasto",
        choices=[("", "Según la categoría"), *Rubro.choices],
        required=False,
    )
    invoice_number = forms.CharField(label="Número de factura", max_length=40, required=False)

    def __init__(self, receipt: Receipt, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        ws = receipt.workspace
        self.fields["category"].queryset = (
            Category.objects.for_workspace(ws)
            .exclude(group=CategoryGroup.INGRESO)
            .filter(is_archived=False)
        )
        self.fields["account"].queryset = Account.objects.for_workspace(ws).filter(
            is_archived=False
        )
        if ws.is_business:
            del self.fields["rubro"]
        data = receipt.extracted
        # El QR de una factura electrónica de la DGII es más confiable que la foto.
        qr = receipt.qr_data or {}
        self.initial.update(
            {
                "description": data.get("comercio") or "",
                "date": qr.get("fecha") or data.get("fecha") or date.today().isoformat(),
                "amount": qr.get("total") or data.get("total"),
                "category": suggested_category(receipt),
                "account": suggested_account(receipt),
                "invoice_number": qr.get("numero") or data.get("numero_factura") or "",
            }
        )
        doubtful = doubtful_fields(data, receipt.field_confidence)
        self.doubtful = {f for f, source in FIELD_SOURCES.items() if source in doubtful}
        for name in self.doubtful:
            widget = self.fields[name].widget
            widget.attrs["class"] = "dudoso"
            widget.attrs["aria-describedby"] = f"dudoso-{name}"
