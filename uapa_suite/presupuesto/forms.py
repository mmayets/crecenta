from datetime import date

from django import forms

from portal.forms import BootstrapMixin

from .models import Departamento, SolicitudCompra


class SolicitudCompraForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = SolicitudCompra
        fields = ["descripcion", "departamento", "monto"]
        labels = {"monto": "Monto (RD$)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["departamento"].queryset = Departamento.objects.filter(anio=date.today().year)
        self.fields["monto"].min_value = 1
        self.fields["monto"].widget.attrs["min"] = 1
