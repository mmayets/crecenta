from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from .models import Aplicacion, Pendiente, Perfil
from .views import saludo


class PortalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("cargar_demo", verbosity=0)
        cls.user = get_user_model().objects.get(username="mmayet")

    def setUp(self):
        self.client.force_login(self.user)

    def test_requiere_acceso(self):
        self.client.logout()
        r = self.client.get(reverse("portal:inicio"))
        self.assertRedirects(r, f"{reverse('login')}?next=/")

    def test_inicio_muestra_suite(self):
        r = self.client.get(reverse("portal:inicio"))
        self.assertContains(r, "Moisés")
        self.assertContains(r, "Mis aplicaciones")
        self.assertContains(r, "Tu Espacio GTH")
        self.assertContains(r, "Próximamente")
        self.assertContains(r, "Aprobar solicitud de compra #2318")
        self.assertContains(r, "Comité académico")
        self.assertContains(r, "Cierre del período de evaluación")

    def test_saludo(self):
        self.assertEqual(saludo(8), "Buenos días")
        self.assertEqual(saludo(15), "Buenas tardes")
        self.assertEqual(saludo(21), "Buenas noches")

    def test_perfil_creado_y_restriccion_de_apps(self):
        perfil = Perfil.objects.get(usuario=self.user)
        perfil.aplicaciones.set([Aplicacion.objects.get(slug="sies")])
        r = self.client.get(reverse("portal:inicio"))
        self.assertNotContains(r, "Planificación y ejecución")
        self.assertContains(r, "Sistema de información estudiantil")

    def test_alternar_pendiente_solo_propio(self):
        p = Pendiente.objects.filter(usuario=self.user).first()
        self.client.post(reverse("portal:alternar_pendiente", args=[p.pk]))
        p.refresh_from_db()
        self.assertTrue(p.completado)
        otro = get_user_model().objects.create_user("otro", password="x-123456789")
        self.client.force_login(otro)
        r = self.client.post(reverse("portal:alternar_pendiente", args=[p.pk]))
        self.assertEqual(r.status_code, 404)

    def test_buscar_json(self):
        r = self.client.get(reverse("portal:buscar"), {"q": "presu"}, HTTP_ACCEPT="application/json")
        tipos = {x["tipo"] for x in r.json()["resultados"]}
        self.assertEqual(tipos, {"Aplicación", "Agenda"})

    def test_marcar_leidas(self):
        self.client.post(reverse("portal:marcar_leidas"))
        self.assertFalse(self.user.notificaciones.filter(leida=False).exists())
