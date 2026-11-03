from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from portal.models import Aplicacion, Aviso, EventoAgenda, Notificacion, Pendiente

APPS = [
    ("PopIn", "popin", "Comunicación institucional", "chat-square-quote", "popin", True),
    ("Tu Espacio GTH", "gth", "Gestión del talento humano", "people", "gth", True),
    ("Presupuesto", "presupuesto", "Planificación y ejecución", "wallet2", "presupuesto", True),
    ("SIES", "sies", "Sistema de información estudiantil", "mortarboard", "sies", True),
    ("Documentos", "documentos", "Gestión documental", "file-earmark-text", "docs", False),
    ("Mesa de ayuda", "mesa-de-ayuda", "Soporte y solicitudes", "life-preserver", "help", False),
]


class Command(BaseCommand):
    help = "Crea aplicaciones, aviso, pendientes y agenda de demostración (idempotente)."

    def add_arguments(self, parser):
        parser.add_argument("--usuario", default="mmayet")
        parser.add_argument("--clave", default="Uapa-Suite-2026")

    @transaction.atomic
    def handle(self, *args, usuario, clave, **opts):
        base = "https://www.uapa.edu.do/"
        apps = {}
        for orden, (nombre, slug, desc, icono, color, disponible) in enumerate(APPS):
            apps[slug], _ = Aplicacion.objects.update_or_create(
                slug=slug,
                defaults=dict(nombre=nombre, descripcion=desc, icono=icono, color=color,
                              disponible=disponible, orden=orden, url=base if disponible else ""),
            )

        Aviso.objects.update_or_create(
            titulo="Cierre del período de evaluación de desempeño: 15 de noviembre",
            defaults=dict(texto="Completa tu autoevaluación en Tu Espacio GTH antes de la fecha límite.",
                          texto_boton="Ir a Tu Espacio GTH", aplicacion=apps["gth"], activo=True),
        )

        User = get_user_model()
        user, creado = User.objects.get_or_create(
            username=usuario, defaults=dict(first_name="Moisés", last_name="Mayet", is_staff=True, is_superuser=True)
        )
        if creado:
            user.set_password(clave)
            user.save()

        user.pendientes.all().delete()
        for titulo, slug in [
            ("Aprobar solicitud de compra #2318", "presupuesto"),
            ("Firmar solicitud de vacaciones", "gth"),
            ("Publicar calificaciones — Cálculo I", "sies"),
            ("Revisar comunicado de bienvenida", "popin"),
        ][::-1]:
            Pendiente.objects.create(usuario=user, aplicacion=apps[slug], titulo=titulo)

        hoy = timezone.localtime().replace(minute=0, second=0, microsecond=0)
        user.eventos.all().delete()
        for hora, minuto, titulo in [(10, 0, "Comité académico"), (13, 30, "Capacitación GTH"), (16, 0, "Revisión presupuestaria")]:
            EventoAgenda.objects.create(usuario=user, titulo=titulo, inicio=hoy.replace(hour=hora, minute=minuto))
        EventoAgenda.objects.create(usuario=user, titulo="Consejo académico", inicio=hoy.replace(hour=9) + timedelta(days=1))

        user.notificaciones.all().delete()
        Notificacion.objects.create(usuario=user, aplicacion=apps["gth"], texto="Tu autoevaluación vence el 15 de noviembre.")
        Notificacion.objects.create(usuario=user, aplicacion=apps["presupuesto"], texto="Nueva solicitud de compra #2318 para aprobar.")

        msg = f"Demo lista. Usuario: {usuario}" + (f" / clave: {clave}" if creado else " (ya existía; clave sin cambios)")
        self.stdout.write(self.style.SUCCESS(msg))
