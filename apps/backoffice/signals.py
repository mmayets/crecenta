"""Entradas, salidas, intentos fallidos y registros nuevos para la auditoría."""

from allauth.account.signals import user_signed_up
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .services.audit import Kind, record


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs) -> None:
    via = "Google" if request is not None and "/google/" in request.path else "correo y contraseña"
    record(kind=Kind.ACCESO, action="inicio_sesion", description=f"Inició sesión ({via})",
           request=request, user=user, status=200, data={"via": via})  # fmt: skip


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs) -> None:
    if user is not None:
        record(kind=Kind.ACCESO, action="cierre_sesion", description="Cerró sesión",
               request=request, user=user, status=200)  # fmt: skip


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs) -> None:
    attempted = str(credentials.get("email") or credentials.get("username") or "")[:254]
    record(kind=Kind.ACCESO, action="inicio_fallido",
           description="Intento de inicio de sesión fallido", request=request,
           user_email=attempted, status=401)  # fmt: skip


@receiver(user_signed_up)
def on_signup(sender, request, user, **kwargs) -> None:
    via = "Google" if kwargs.get("sociallogin") else "correo"
    record(kind=Kind.ACCESO, action="registro", description=f"Creó su cuenta ({via})",
           request=request, user=user, status=200, data={"via": via})  # fmt: skip
