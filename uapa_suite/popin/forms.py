from django import forms

from portal.forms import BootstrapMixin

from .models import Comentario, Comunicado


class ComunicadoForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Comunicado
        fields = ["tipo", "titulo", "area", "resumen", "cuerpo"]
        widgets = {"cuerpo": forms.Textarea(attrs={"rows": 6}), "resumen": forms.Textarea(attrs={"rows": 2})}


class ComentarioForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Comentario
        fields = ["texto"]
        labels = {"texto": ""}
        widgets = {"texto": forms.Textarea(attrs={"rows": 2, "placeholder": "Escribe un comentario…"})}
