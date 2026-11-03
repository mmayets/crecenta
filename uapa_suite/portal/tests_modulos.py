from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from gth.models import Solicitud
from popin.models import Comunicado
from portal.models import Aplicacion, Perfil
from portal.templatetags.suite import rd
from presupuesto.models import SolicitudCompra, totales
from sies.models import Seccion

User = get_user_model()


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("cargar_demo", verbosity=0, personal=10)
        cls.user = User.objects.get(username="mmayet")

    def setUp(self):
        self.client.force_login(self.user)


class NavegacionTests(Base):
    def test_paginas_de_modulos_responden(self):
        for nombre in [
            "popin:inicio", "popin:noticias", "popin:eventos", "popin:encuestas", "popin:guardados", "popin:nuevo",
            "gth:inicio", "gth:solicitudes", "gth:vacaciones", "gth:volantes", "gth:evaluacion",
            "gth:capacitaciones", "gth:certificaciones", "gth:nueva_solicitud",
            "presupuesto:inicio", "presupuesto:solicitudes", "presupuesto:partidas", "presupuesto:reportes",
            "presupuesto:proveedores", "presupuesto:nueva_solicitud",
            "sies:inicio", "sies:calificaciones", "sies:asistencia", "sies:estudiantes", "sies:calendario",
        ]:
            with self.subTest(nombre):
                self.assertEqual(self.client.get(reverse(nombre)).status_code, 200)

    def test_tarjetas_de_portada_llevan_a_modulos_internos(self):
        r = self.client.get(reverse("portal:inicio"))
        for slug in ["popin", "gth", "presupuesto", "sies"]:
            self.assertContains(r, f'href="/{slug}/"')
        self.assertContains(r, 'id="info"')

    def test_marco_del_modulo(self):
        r = self.client.get(reverse("gth:inicio"))
        self.assertContains(r, "crumb-actual")
        self.assertContains(r, "¿Necesitas ayuda con Tu Espacio GTH?")
        self.assertContains(r, 'class="subnav-link active"')

    def test_aplicacion_externa_abre_en_otra_pestana(self):
        Aplicacion.objects.filter(slug="sies").update(url="https://sies.example.edu")
        r = self.client.get(reverse("portal:inicio"))
        self.assertContains(r, 'href="https://sies.example.edu" target="_blank"')

    def test_modulo_no_asignado_da_403(self):
        Perfil.objects.get(usuario=self.user).aplicaciones.set([Aplicacion.objects.get(slug="gth")])
        self.assertEqual(self.client.get(reverse("presupuesto:inicio")).status_code, 403)
        self.assertEqual(self.client.get(reverse("gth:inicio")).status_code, 200)

    def test_requiere_acceso(self):
        self.client.logout()
        r = self.client.get(reverse("sies:inicio"))
        self.assertEqual(r.status_code, 302)


class PopInTests(Base):
    def test_indicadores_y_contadores(self):
        r = self.client.get(reverse("popin:inicio"))
        self.assertEqual(r.context["kpi"]["publicados"], 9)
        self.assertEqual(r.context["kpi"]["sin_leer"], 5)
        self.assertEqual(r.context["kpi"]["variacion"], "+12% vs. mes anterior")
        badges = {i.etiqueta: i.badge for i in r.context["modulo_nav"]}
        self.assertEqual((badges["Noticias"], badges["Encuestas"]), (3, 1))
        titulos = [c.titulo for c in r.context["comunicados"]]
        self.assertEqual(titulos[0], "Bienvenida al nuevo trimestre académico")

    def test_leer_reaccionar_guardar_y_comentar(self):
        c = Comunicado.objects.get(titulo__startswith="Bienvenida")
        self.client.get(reverse("popin:detalle", args=[c.pk]))
        self.assertTrue(c.leido_por.filter(pk=self.user.pk).exists())
        self.client.post(reverse("popin:me_gusta", args=[c.pk]))
        self.assertTrue(c.me_gusta.filter(pk=self.user.pk).exists())
        self.client.post(reverse("popin:me_gusta", args=[c.pk]))
        self.assertFalse(c.me_gusta.filter(pk=self.user.pk).exists())
        self.client.post(reverse("popin:guardar", args=[c.pk]))
        self.assertContains(self.client.get(reverse("popin:guardados")), c.titulo)
        self.client.post(reverse("popin:detalle", args=[c.pk]), {"texto": "Gracias"})
        self.assertTrue(c.comentarios.filter(usuario=self.user, texto="Gracias").exists())

    def test_nuevo_comunicado_requiere_permiso(self):
        otro = User.objects.create_user("lector", password="x-123456789")
        self.client.force_login(otro)
        self.assertEqual(self.client.get(reverse("popin:nuevo")).status_code, 403)
        self.assertNotContains(self.client.get(reverse("popin:inicio")), "Nuevo comunicado")

    def test_publicar_comunicado(self):
        r = self.client.post(reverse("popin:nuevo"), {"tipo": "comunicado", "titulo": "Prueba", "area": "TIC",
                                                       "resumen": "Texto", "cuerpo": ""})
        c = Comunicado.objects.get(titulo="Prueba")
        self.assertRedirects(r, reverse("popin:detalle", args=[c.pk]))
        self.assertEqual(c.autor, self.user)


class GTHTests(Base):
    def test_resumen(self):
        r = self.client.get(reverse("gth:inicio"))
        self.assertEqual(r.context["horas"], 36)
        self.assertEqual(r.context["antiguedad"], "6 años")
        self.assertContains(r, "Vence 15 nov")
        self.assertContains(r, "Vacaciones 20–24 dic")

    def test_nueva_solicitud_valida_fechas_de_vacaciones(self):
        url = reverse("gth:nueva_solicitud")
        r = self.client.post(url, {"tipo": "vacaciones", "descripcion": "Playa"})
        self.assertContains(r, "Indica las fechas")
        r = self.client.post(url, {"tipo": "vacaciones", "descripcion": "Playa",
                                   "fecha_inicio": "2026-12-10", "fecha_fin": "2026-12-01"})
        self.assertContains(r, "no puede ser anterior")
        r = self.client.post(url, {"tipo": "vacaciones", "descripcion": "Playa",
                                   "fecha_inicio": "2026-12-01", "fecha_fin": "2026-12-05"})
        self.assertRedirects(r, reverse("gth:inicio"))
        self.assertEqual(Solicitud.objects.get(descripcion="Playa").estado, "pendiente")


class PresupuestoTests(Base):
    def test_totales_y_tablero(self):
        t = totales(date.today().year)
        self.assertEqual(t["aprobado"], Decimal(412_000_000))
        self.assertEqual(t["disponible"], Decimal(83_000_000))
        self.assertEqual(t["porcentaje"], Decimal("65.8"))
        r = self.client.get(reverse("presupuesto:inicio"), {"anio": str(date.today().year)})
        self.assertContains(r, "RD$ 412M")
        self.assertContains(r, "65.8% del total")
        self.assertEqual([d.porcentaje_ejecutado for d in r.context["departamentos"]], [78, 62, 45, 88, 54])

    def test_anio_invalido_no_rompe(self):
        self.assertEqual(self.client.get(reverse("presupuesto:inicio"), {"anio": "abc"}).status_code, 200)

    def test_formato_compacto(self):
        self.assertEqual(rd(Decimal("1200000")), "RD$ 1.2M")
        self.assertEqual(rd(Decimal("640000")), "RD$ 640K")
        self.assertEqual(rd(Decimal("412000000")), "RD$ 412M")
        self.assertEqual(rd(Decimal("950")), "RD$ 950")

    def test_nueva_solicitud_numera_y_decidir(self):
        depto = self.client.get(reverse("presupuesto:nueva_solicitud")).context["form"].fields["departamento"].queryset.first()
        self.client.post(reverse("presupuesto:nueva_solicitud"),
                         {"descripcion": "Proyectores", "departamento": depto.pk, "monto": "50000"})
        s = SolicitudCompra.objects.get(descripcion="Proyectores")
        self.assertEqual(s.numero, 2319)
        self.client.post(reverse("presupuesto:decidir", args=[2319]), {"estado": "aprobado"})
        s.refresh_from_db()
        self.assertEqual(s.estado, "aprobado")

    def test_decidir_requiere_permiso(self):
        self.client.force_login(User.objects.create_user("analista", password="x-123456789"))
        r = self.client.post(reverse("presupuesto:decidir", args=[2318]), {"estado": "aprobado"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(SolicitudCompra.objects.get(numero=2318).estado, "pendiente")

    def test_exportar_partidas(self):
        r = self.client.get(reverse("presupuesto:exportar_partidas"), {"anio": str(date.today().year)})
        self.assertEqual(r["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("Académico", r.content.decode("utf-8-sig"))


class SIESTests(Base):
    def test_tablero(self):
        r = self.client.get(reverse("sies:inicio"))
        self.assertEqual(r.context["inscritos"], 144)
        self.assertEqual(r.context["asistencia_texto"], "91%")
        self.assertEqual(r.context["nota_por_publicar"], "Cálculo I")
        self.assertEqual(r.context["secciones"][0].codigo, "MAT-101")

    def test_publicar_calificaciones(self):
        self.client.post(reverse("sies:publicar"))
        self.assertFalse(Seccion.objects.filter(docente=self.user, calificaciones="pendiente").exists())
        self.assertEqual(Seccion.objects.get(codigo="MAT-101").calificaciones, "en_curso")

    def test_solo_ve_sus_secciones_y_exporta(self):
        otro = User.objects.create_user("docente2", password="x-123456789")
        Seccion.objects.create(docente=otro, trimestre="x", codigo="QUI-100", asignatura="Química", numero=1)
        r = self.client.get(reverse("sies:exportar"))
        texto = r.content.decode("utf-8-sig")
        self.assertIn("MAT-101", texto)
        self.assertNotIn("QUI-100", texto)
