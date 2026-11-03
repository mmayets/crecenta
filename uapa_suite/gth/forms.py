from django import forms

from portal.forms import BootstrapMixin

from .models import Solicitud


class SolicitudForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Solicitud
        fields = ["tipo", "descripcion", "fecha_inicio", "fecha_fin"]
        widgets = {
            "fecha_inicio": forms.DateInput(attrs={"type": "date"}),
            "fecha_fin": forms.DateInput(attrs={"type": "date"}),
        }

    def clean(self):
        datos = super().clean()
        inicio, fin = datos.get("fecha_inicio"), datos.get("fecha_fin")
        if datos.get("tipo") == Solicitud.Tipo.VACACIONES and not (inicio and fin):
            raise forms.ValidationError("Indica las fechas de inicio y fin de las vacaciones.")
        if inicio and fin and fin < inicio:
            raise forms.ValidationError("La fecha de fin no puede ser anterior a la de inicio.")
        return datos
