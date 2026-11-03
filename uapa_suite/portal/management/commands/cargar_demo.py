"""Datos de demostración de toda la suite (idempotente: se puede ejecutar varias veces)."""

import random
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from gth.models import Capacitacion, Evaluacion, FichaColaborador, Inscripcion, Solicitud
from popin.models import Comentario, Comunicado
from portal.models import Aplicacion, Aviso, EventoAgenda, Notificacion, Pendiente
from presupuesto.models import Departamento, SolicitudCompra
from sies.models import Seccion

APPS = [
    ("PopIn", "popin", "Comunicación institucional", "chat-square-quote", "popin", True),
    ("Tu Espacio GTH", "gth", "Gestión del talento humano", "people", "gth", True),
    ("Presupuesto", "presupuesto", "Planificación y ejecución", "wallet2", "presupuesto", True),
    ("SIES", "sies", "Sistema de información estudiantil", "mortarboard", "sies", True),
    ("Documentos", "documentos", "Gestión documental", "file-earmark-text", "docs", False),
    ("Mesa de ayuda", "mesa-de-ayuda", "Soporte y solicitudes", "life-preserver", "help", False),
]

# (tipo, título, área, resumen, ¿leído por el usuario demo?)
PUBLICACIONES_MES = [
    ("comunicado", "Mantenimiento programado de plataformas", "TIC",
     "El sábado de 10 pm a 2 am algunos servicios estarán temporalmente fuera de línea.", True),
    ("comunicado", "Jornada de salud ocupacional", "Gestión Humana",
     "Este viernes estaremos realizando chequeos preventivos en el edificio principal.", True),
    ("noticia", "UAPA recibe acreditación internacional de sus programas virtuales", "Rectoría",
     "La agencia evaluadora reconoció la calidad de la oferta académica a distancia.", False),
    ("noticia", "Nueva biblioteca digital disponible para toda la comunidad", "Biblioteca",
     "Más de 40 000 títulos accesibles desde la plataforma con tu cuenta institucional.", False),
    ("noticia", "Egresados UAPA destacan en concurso nacional de innovación", "Extensión",
     "Tres proyectos de nuestros egresados quedaron entre los diez finalistas.", False),
    ("evento", "Feria de emprendimiento estudiantil", "Extensión",
     "Jueves 20 de noviembre, de 9:00 a 4:00 en el campus principal.", True),
    ("evento", "Taller de bienestar emocional", "Gestión Humana",
     "Sesión virtual abierta a todo el personal el miércoles a las 3:00 p. m.", True),
    ("encuesta", "Encuesta de clima organizacional 2026", "Gestión Humana",
     "Tu opinión nos ayuda a mejorar. Toma menos de 10 minutos.", False),
    ("comunicado", "Bienvenida al nuevo trimestre académico", "Rectoría",
     "Iniciamos un nuevo período con grandes retos y oportunidades para toda la comunidad.", False),
]
PUBLICACIONES_MES_ANTERIOR = [
    ("comunicado", "Calendario de cierre del trimestre agosto – octubre", "Registro"),
    ("comunicado", "Actualización de la política de teletrabajo", "Gestión Humana"),
    ("noticia", "Inauguración del laboratorio de IA y Big Data", "Rectoría"),
    ("noticia", "Convenio con universidades de la región", "Relaciones Internacionales"),
    ("evento", "Semana de la investigación", "Investigación"),
    ("evento", "Torneo deportivo interdepartamental", "Extensión"),
    ("encuesta", "Evaluación de los servicios de cafetería", "Administración"),
    ("comunicado", "Horario especial por día feriado", "Rectoría"),
]
COMENTARIOS = ["¡Excelente noticia!", "Gracias por la información.", "Muy oportuno, gracias.",
               "¿Habrá una sesión de seguimiento?", "Contamos con ello.", "Felicidades a todo el equipo."]

DEPARTAMENTOS = [  # nombre, aprobado, ejecutado, comprometido (millones de RD$)
    ("Académico", "131", "102.8", "20"),
    ("Tecnología", "95", "58.9", "14"),
    ("Gestión Humana", "71", "31.9", "8"),
    ("Extensión", "45", "39.6", "6"),
    ("Administración", "70", "37.8", "10"),
]


class Command(BaseCommand):
    help = "Crea datos de demostración para la portada y los módulos (idempotente)."

    def add_arguments(self, parser):
        parser.add_argument("--usuario", default="mmayet")
        parser.add_argument("--clave", default="Uapa-Suite-2026")
        parser.add_argument("--personal", type=int, default=40, help="Colaboradores ficticios para lecturas y reacciones.")

    @transaction.atomic
    def handle(self, *args, usuario, clave, personal, **opts):
        rnd = random.Random(2026)
        ahora = timezone.localtime()
        hoy = ahora.date()
        User = get_user_model()

        apps = {}
        for orden, (nombre, slug, desc, icono, color, disponible) in enumerate(APPS):
            apps[slug], _ = Aplicacion.objects.update_or_create(
                slug=slug,
                defaults=dict(nombre=nombre, descripcion=desc, icono=icono, color=color, disponible=disponible,
                              orden=orden, url=""),
            )

        Aviso.objects.update_or_create(
            titulo="Cierre del período de evaluación de desempeño: 15 de noviembre",
            defaults=dict(texto="Completa tu autoevaluación en Tu Espacio GTH antes de la fecha límite.",
                          texto_boton="Ir a Tu Espacio GTH", aplicacion=apps["gth"], activo=True),
        )

        user, creado = User.objects.get_or_create(
            username=usuario, defaults=dict(first_name="Moisés", last_name="Mayet", is_staff=True, is_superuser=True)
        )
        if creado:
            user.set_password(clave)
            user.save()

        equipo = []
        for i in range(1, personal + 1):
            u, nuevo = User.objects.get_or_create(
                username=f"colaborador{i:02d}", defaults=dict(first_name=f"Colaborador {i:02d}")
            )
            if nuevo:
                u.set_unusable_password()
                u.save()
            equipo.append(u)

        # ---------- PopIn ----------
        def publicar(tipo, titulo, area, resumen, fecha):
            c, _ = Comunicado.objects.update_or_create(
                titulo=titulo, defaults=dict(tipo=tipo, area=area, resumen=resumen, publicado=fecha, autor=user)
            )
            c.me_gusta.set(rnd.sample(equipo, rnd.randint(len(equipo) // 4, len(equipo) * 9 // 10)))
            c.leido_por.set([u for u in equipo if rnd.random() < 0.88])
            c.comentarios.all().delete()
            for k in range(rnd.randint(1, 4)):
                Comentario.objects.create(comunicado=c, usuario=rnd.choice(equipo), texto=COMENTARIOS[k])
            return c

        inicio_mes = ahora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        paso = (ahora - inicio_mes) / (len(PUBLICACIONES_MES) + 1)
        bienvenida = None
        for n, (tipo, titulo, area, resumen, leido) in enumerate(PUBLICACIONES_MES, start=1):
            c = publicar(tipo, titulo, area, resumen, inicio_mes + paso * n)
            if leido:
                c.leido_por.add(user)
            if titulo.startswith("Bienvenida"):
                bienvenida = c
        mes_anterior = (inicio_mes - timedelta(days=1)).replace(day=1)
        for n, (tipo, titulo, area) in enumerate(PUBLICACIONES_MES_ANTERIOR):
            c = publicar(tipo, titulo, area, f"{titulo}. Consulta los detalles en el comunicado.",
                         mes_anterior + timedelta(days=2 + n * 3))
            c.leido_por.add(user)

        # ---------- Tu Espacio GTH ----------
        FichaColaborador.objects.update_or_create(
            usuario=user,
            defaults=dict(fecha_ingreso=hoy.replace(year=hoy.year - 6) - timedelta(days=30), dias_vacaciones=14,
                          meta_horas_capacitacion=40),
        )
        user.solicitudes_gth.all().delete()
        for tipo, desc, estado, ini, fin in [
            ("horario", "Cambio de horario", "rechazado", None, None),
            ("permiso", "Permiso médico", "aprobado", None, None),
            ("carta", "Carta de trabajo", "aprobado", None, None),
            ("vacaciones", "Vacaciones 20–24 dic", "pendiente", date(hoy.year, 12, 20), date(hoy.year, 12, 24)),
        ]:
            Solicitud.objects.create(usuario=user, tipo=tipo, descripcion=desc, estado=estado,
                                     fecha_inicio=ini, fecha_fin=fin)
        user.capacitaciones.all().delete()
        for nombre, horas, progreso in [("Liderazgo de equipos", 20, 70), ("Excel avanzado", 16, 35),
                                        ("Atención al estudiante", 16, 100)]:
            cap, _ = Capacitacion.objects.update_or_create(nombre=nombre, defaults={"horas": horas})
            Inscripcion.objects.create(usuario=user, capacitacion=cap, progreso=progreso, anio=hoy.year)
        Evaluacion.objects.update_or_create(
            usuario=user, anio=hoy.year, defaults=dict(vence=date(hoy.year, 11, 15), completada=False)
        )

        # ---------- Presupuesto ----------
        millon = Decimal(1_000_000)
        deptos = {}
        for orden, (nombre, aprobado, ejecutado, comprometido) in enumerate(DEPARTAMENTOS):
            deptos[nombre], _ = Departamento.objects.update_or_create(
                nombre=nombre, anio=hoy.year,
                defaults=dict(aprobado=Decimal(aprobado) * millon, ejecutado=Decimal(ejecutado) * millon,
                              comprometido=Decimal(comprometido) * millon, orden=orden),
            )
        for numero, desc, depto, monto, estado in [
            (2311, "Viáticos congreso", "Académico", "120000", "rechazado"),
            (2315, "Mobiliario aulas", "Administración", "980000", "en_curso"),
            (2317, "Licencias software", "Tecnología", "640000", "aprobado"),
            (2318, "Equipos de laboratorio", "Académico", "1200000", "pendiente"),
        ]:
            SolicitudCompra.objects.update_or_create(
                numero=numero,
                defaults=dict(descripcion=desc, departamento=deptos[depto], monto=Decimal(monto), estado=estado,
                              solicitante=user),
            )

        # ---------- SIES ----------
        user.secciones.all().delete()
        for codigo, asignatura, numero, inscritos, nuevos, asistencia, estado in [
            ("MAT-101", "Cálculo I", 3, 38, 3, 89, "pendiente"),
            ("FIS-110", "Física General", 1, 42, 2, 93, "aprobado"),
            ("EST-201", "Estadística", 2, 35, 2, 90, "en_curso"),
            ("INF-220", "Base de Datos", 5, 29, 1, 92, "aprobado"),
        ]:
            Seccion.objects.create(docente=user, trimestre=f"noviembre – enero {hoy.year + 1}", codigo=codigo,
                                   asignatura=asignatura, numero=numero, inscritos=inscritos, nuevos=nuevos,
                                   asistencia=asistencia, calificaciones=estado)

        # ---------- Portada ----------
        user.pendientes.all().delete()
        for titulo, slug, url in [
            ("Revisar comunicado de bienvenida", "popin", reverse("popin:detalle", args=[bienvenida.pk])),
            ("Publicar calificaciones — Cálculo I", "sies", reverse("sies:calificaciones")),
            ("Firmar solicitud de vacaciones", "gth", reverse("gth:vacaciones")),
            ("Aprobar solicitud de compra #2318", "presupuesto", reverse("presupuesto:solicitudes") + "?estado=pendiente"),
        ]:
            Pendiente.objects.create(usuario=user, aplicacion=apps[slug], titulo=titulo, url=url)

        base = ahora.replace(minute=0, second=0, microsecond=0)
        user.eventos.all().delete()
        for hora, minuto, titulo in [(10, 0, "Comité académico"), (13, 30, "Capacitación GTH"), (16, 0, "Revisión presupuestaria")]:
            EventoAgenda.objects.create(usuario=user, titulo=titulo, inicio=base.replace(hour=hora, minute=minuto))
        EventoAgenda.objects.create(usuario=user, titulo="Consejo académico", inicio=base.replace(hour=9) + timedelta(days=1))

        user.notificaciones.all().delete()
        Notificacion.objects.create(usuario=user, aplicacion=apps["gth"], texto="Tu autoevaluación vence el 15 de noviembre.")
        Notificacion.objects.create(usuario=user, aplicacion=apps["presupuesto"], texto="Nueva solicitud de compra #2318 para aprobar.")

        msg = f"Demo lista. Usuario: {usuario}" + (f" / clave: {clave}" if creado else " (ya existía; clave sin cambios)")
        if opts.get("verbosity", 1):
            self.stdout.write(self.style.SUCCESS(msg))
