import re

from django import forms

from apps.core.models import Parameter

SECRET = re.compile(r"(SECRET|KEY|PASSWORD|TOKEN)", re.IGNORECASE)
KEY = re.compile(r"^[A-Z][A-Z0-9_]{1,99}$")


def is_secret(key: str) -> bool:
    return bool(SECRET.search(key or ""))


class ParameterForm(forms.ModelForm):
    """Alta y edición de parámetros. Los valores secretos no se muestran: dejarlos vacíos al
    editar conserva el valor actual."""

    class Meta:
        model = Parameter
        fields = ["key", "value", "description"]
        labels = {"key": "Clave", "value": "Valor", "description": "Para qué sirve (opcional)"}
        widgets = {"value": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.secret = is_secret(self.instance.key or self.data.get("key", ""))
        self.editing = not self.instance._state.adding  # el UUID existe aunque no esté guardado
        if self.editing:
            self.fields["key"].disabled = True
            if self.secret:
                self.fields["value"].widget = forms.PasswordInput(
                    render_value=False, attrs={"autocomplete": "new-password"}
                )
                self.fields["value"].required = False
                self.fields["value"].help_text = "Déjalo vacío para conservar el valor actual."

    def clean_key(self) -> str:
        key = self.cleaned_data["key"].strip().upper()
        if not KEY.match(key):
            raise forms.ValidationError(
                "Usa mayúsculas, números y guiones bajos (ej.: AI_PROVIDER)."
            )
        if key in {"DATABASE_URL", "DJANGO_SETTINGS_MODULE", "POSTGRES_ADMIN_URL"}:
            raise forms.ValidationError("Esta clave se configura fuera de la base de datos.")
        return key

    def clean_value(self) -> str:
        value = self.cleaned_data.get("value", "")
        if self.editing and self.secret and not value:
            return self.instance.value
        return value


class PushForm(forms.Form):
    """Mensaje push desde el panel: a todas las personas suscritas o a una sola."""

    destino = forms.ChoiceField(
        label="Para",
        choices=[
            ("todos", "Todas las personas con notificaciones activas"),
            ("una", "Una persona"),
        ],
        widget=forms.RadioSelect,
        initial="todos",
    )
    correo = forms.EmailField(label="Correo de la persona", required=False)
    titulo = forms.CharField(label="Título", max_length=80)
    mensaje = forms.CharField(
        label="Mensaje", max_length=240, widget=forms.Textarea(attrs={"rows": 3})
    )
    enlace = forms.CharField(
        label="Al tocarla, abrir (opcional)",
        max_length=200,
        required=False,
        help_text="Una dirección de la app, por ejemplo / o /cuenta/configuracion/.",
    )

    def clean_enlace(self) -> str:
        link = self.cleaned_data.get("enlace", "").strip() or "/"
        if not link.startswith("/") or link.startswith("//"):
            raise forms.ValidationError("Usa una dirección de la app que empiece con /.")
        return link

    def clean(self) -> dict:
        data = super().clean()
        if data.get("destino") == "una" and not data.get("correo"):
            self.add_error("correo", "Escribe el correo de la persona.")
        return data
