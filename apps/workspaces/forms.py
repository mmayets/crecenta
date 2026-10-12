from django import forms

from apps.core.money import CURRENCY_CHOICES


class UsageForm(forms.Form):
    """Paso 0: ¿Para qué usarás la app?"""

    USAGE_CHOICES = [
        ("persona", "Mis finanzas personales"),
        ("negocio", "Mi emprendimiento o negocio"),
        ("ambos", "Ambos"),
    ]

    usage = forms.ChoiceField(
        label="¿Para qué usarás la app?", choices=USAGE_CHOICES, widget=forms.RadioSelect
    )
    currency = forms.ChoiceField(label="Moneda", choices=CURRENCY_CHOICES, initial="DOP")
    business_name = forms.CharField(label="Nombre del negocio", max_length=80, required=False)
