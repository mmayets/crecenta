from django import forms

from .models import User


class SettingsForm(forms.ModelForm):
    ai_consent = forms.BooleanField(
        label="Permitir el uso de IA (leer comprobantes, entender texto y voz, explicar mi plan)",
        required=False,
    )

    class Meta:
        model = User
        fields = ["first_name"]
        labels = {"first_name": "¿Cómo te llamamos?"}


class DeleteAccountForm(forms.Form):
    confirm_email = forms.EmailField(label="Escribe tu correo para confirmar")
    password = forms.CharField(label="Tu contraseña", widget=forms.PasswordInput, required=False)

    def __init__(self, user: User, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.user = user
        if user.has_usable_password():
            self.fields["password"].required = True
        else:  # cuenta creada con Google: basta con el correo
            del self.fields["password"]

    def clean_password(self) -> str:
        password = self.cleaned_data.get("password", "")
        if not self.user.check_password(password):
            raise forms.ValidationError("La contraseña no es correcta.")
        return password

    def clean_confirm_email(self) -> str:
        value = self.cleaned_data["confirm_email"].strip().lower()
        if value != self.user.email.lower():
            raise forms.ValidationError("El correo no coincide con el de tu cuenta.")
        return value
