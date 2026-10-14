import pytest
from django.urls import reverse

from apps.ai.models import AIInteraction
from apps.ai.providers import FakeProvider, ProviderError
from apps.onboarding.models import AssistantSession
from apps.onboarding.services import assistant
from apps.onboarding.services.steps import get_state
from apps.onboarding.tests.test_conversational import EXTRACCION
from apps.workspaces.models import Workspace

pytestmark = pytest.mark.django_db

Stage = AssistantSession.Stage
CHAT = reverse("asistente:chat")


def say(client, text):
    return client.post(CHAT, {"texto": text})


def session_of(user):
    return AssistantSession.objects.get(user=user)


# ---------------------------------------------------------------- reglas (sin IA)


@pytest.mark.parametrize(
    ("text", "pending", "expected"),
    [
        ("Mi dinero personal", ["uso"], {"uso": "persona"}),
        ("mi negocio de postres, en dólares", ["uso"], {"uso": "negocio", "moneda": "USD"}),
        ("Ambos", ["uso"], {"uso": "ambos"}),
        ("mis gastos y mi tienda", ["uso"], {"uso": "ambos"}),
        (
            "Tienda La Esquina",
            ["nombre_negocio", "moneda"],
            {"nombre_negocio": "Tienda La Esquina"},
        ),
        ("se llama Dulces Ana.", ["uso"], {"nombre_negocio": "Dulces Ana"}),
        ("Pesos (RD$)", ["moneda"], {"moneda": "DOP"}),
        ("no sé", ["uso"], {}),
    ],
)
def test_reglas_entienden_respuestas_simples(text, pending, expected):
    turn = assistant.interpret_by_rules(text, pending)
    found = {k: v for k, v in turn.model_dump().items() if v}
    assert found == expected


# ---------------------------------------------------------------- crear el espacio


def test_el_chat_saluda_y_no_crea_nada(client, user):
    client.force_login(user)
    html = client.get(CHAT).content.decode()
    assert "¿Qué quieres organizar" in html and "Mi negocio" in html
    assert not Workspace.objects.filter(owner=user).exists()


def test_sin_consentimiento_funciona_con_reglas_y_crea_al_confirmar(client, user):
    client.force_login(user)
    say(client, "Ambos")
    session = session_of(user)
    assert session.stage == Stage.CHAT and session.draft == {"uso": "ambos"}
    assert session.messages[-1]["texto"] == assistant.QUESTIONS["nombre_negocio"]

    say(client, "Dulces Ana")
    say(client, "Pesos (RD$)")
    session.refresh_from_db()
    assert session.stage == Stage.SUMMARY
    # Conversar nunca crea: hace falta el botón.
    assert not Workspace.objects.filter(owner=user).exists()
    page = client.get(CHAT).content.decode()
    assert 'data-testid="resumen"' in page and "Dulces Ana" in page

    response = client.post(reverse("asistente:create"))
    assert response["Location"] == CHAT
    negocio = Workspace.objects.get(owner=user, kind="business")
    personal = Workspace.objects.get(owner=user, kind="personal")
    assert (negocio.name, negocio.currency, personal.currency) == ("Dulces Ana", "DOP", "DOP")
    session.refresh_from_db()
    assert session.stage == Stage.FILLING
    assert session.queue == [str(personal.pk), str(negocio.pk)]
    # Ninguna llamada salió hacia el proveedor.
    assert not FakeProvider.calls
    assert set(AIInteraction.objects.values_list("outcome", flat=True)) == {"sin_consentimiento"}


def test_crear_sin_resumen_no_hace_nada(client, user):
    client.force_login(user)
    say(client, "Mi negocio")
    client.post(reverse("asistente:create"))
    assert not Workspace.objects.filter(owner=user).exists()
    assert session_of(user).stage == Stage.CHAT


def test_con_ia_usa_lo_que_entendio_y_su_mensaje(client, user):
    user.set_ai_consent(True)
    client.force_login(user)
    FakeProvider.queue(
        {
            "mensaje": "¡Qué rico! ¿En qué moneda cobras?",
            "uso": "negocio",
            "nombre_negocio": "Dulces Ana",
        }
    )
    say(client, "vendo postres, el negocio se llama Dulces Ana")
    session = session_of(user)
    assert session.draft == {"uso": "negocio", "nombre_negocio": "Dulces Ana"}
    assert session.messages[-1]["texto"] == "¡Qué rico! ¿En qué moneda cobras?"

    # La IA dice que todo está listo, pero el servidor decide: con moneda ya hay resumen.
    FakeProvider.queue({"mensaje": "Listo, ya lo creé.", "moneda": "USD"})
    say(client, "en dólares")
    session.refresh_from_db()
    assert session.stage == Stage.SUMMARY
    assert "pulsa «Crear»" in session.messages[-1]["texto"]
    assert not Workspace.objects.filter(owner=user).exists()


def test_ia_caida_degrada_a_reglas(client, user):
    user.set_ai_consent(True)
    client.force_login(user)
    FakeProvider.queue(ProviderError("sin red"), ProviderError("sin red"))
    say(client, "Mi dinero personal")
    session = session_of(user)
    assert session.draft == {"uso": "persona"}
    assert session.messages[-1]["texto"] == assistant.QUESTIONS["moneda"]


def test_corregir_en_el_resumen(client, user):
    client.force_login(user)
    for text in ("Mi negocio", "Dulces Ana", "pesos"):
        say(client, text)
    say(client, "mejor en dólares")
    session = session_of(user)
    assert session.stage == Stage.SUMMARY and session.draft["moneda"] == "USD"
    client.post(reverse("asistente:create"))
    assert Workspace.objects.get(owner=user).currency == "USD"


def test_no_duplica_un_espacio_que_ya_existe(client, user, personal_ws):
    client.force_login(user)
    say(client, "Mi dinero personal")
    session = session_of(user)
    assert session.stage == Stage.CHAT and "uso" not in session.draft
    assert session.messages[-1]["enlaces"][0]["url"] == reverse(
        "espacio:dashboard", args=[personal_ws.pk]
    )
    # «Ambos» crea solo lo que falta.
    for text in ("Ambos", "Dulces Ana", "pesos"):
        say(client, text)
    client.post(reverse("asistente:create"))
    assert Workspace.objects.filter(owner=user).count() == 2
    assert session_of(user).queue == [str(Workspace.objects.get(owner=user, kind="business").pk)]


def test_htmx_recibe_solo_el_panel(client, user):
    client.force_login(user)
    response = client.post(CHAT, {"texto": "Ambos"}, headers={"HX-Request": "true"})
    html = response.content.decode()
    assert response.status_code == 200
    assert html.lstrip().startswith('<div id="asistente"') and "<html" not in html
    assert 'data-testid="borrador-uso">Mi dinero y mi negocio' in html


def test_reiniciar_borra_el_borrador(client, user):
    client.force_login(user)
    say(client, "Ambos")
    client.post(reverse("asistente:restart"))
    session = session_of(user)
    assert session.draft == {} and len(session.messages) == 1


def test_limite_de_turnos(client, user):
    client.force_login(user)
    session = assistant.get_or_start(user)
    session.turns = assistant.MAX_TURNS
    session.save()
    say(client, "Ambos")
    session.refresh_from_db()
    assert session.draft == {}
    assert session.messages[-1]["enlaces"][0]["url"] == reverse("workspaces:usage")


def test_anonimo_va_a_login(client):
    assert reverse("account_login") in client.get(CHAT)["Location"]
    assert reverse("account_login") in client.post(reverse("asistente:create"))["Location"]


def test_cada_persona_ve_solo_su_conversacion(client, user, other_user):
    client.force_login(user)
    say(client, "se llama Dulces Ana")
    client.force_login(other_user)
    assert "Dulces Ana" not in client.get(CHAT).content.decode()


# ---------------------------------------------------------------- llenado guiado


@pytest.fixture
def filling(client, user):
    """Sesión con el espacio personal recién creado desde el chat."""
    client.force_login(user)
    for text in ("Mi dinero personal", "pesos"):
        say(client, text)
    client.post(reverse("asistente:create"))
    return Workspace.objects.get(owner=user, kind="personal")


def test_llenado_sin_ia_ofrece_activarla_o_el_formulario(client, user, filling):
    assert "Permitir el uso de IA" in client.get(CHAT).content.decode()
    say(client, "cobro 50 mil el 30")
    last = session_of(user).messages[-1]
    assert "Activa el uso de IA" in last["texto"]
    assert last["enlaces"][0]["url"] == reverse("onboarding:index", args=[filling.pk])

    client.post(reverse("asistente:enable_ai"))
    user.refresh_from_db()
    assert user.ai_consent
    assert "Permitir el uso de IA" not in client.get(CHAT).content.decode()


def test_llenado_extrae_confirma_y_termina(client, user, filling):
    user.set_ai_consent(True)
    FakeProvider.queue(EXTRACCION)
    say(client, "Cobro 50 mil el día 30, pago 18 mil de alquiler el 5…")
    last = session_of(user).messages[-1]
    confirm_url = reverse("onboarding:confirm", args=[filling.pk])
    assert "1 ingreso, 2 cuentas, 2 pagos fijos" in last["texto"]
    assert last["enlaces"] == [{"texto": "Revisar y guardar", "url": confirm_url}]
    # Nada es dato de dominio todavía: queda pendiente de confirmar.
    state = get_state(filling)
    assert state.pending_extraction and not state.answered_steps
    assert assistant.after_confirm_url(user, filling) == CHAT
    client.get(CHAT)
    assert session_of(user).stage == Stage.FILLING

    # La pantalla de confirmación guarda y marca los pasos; al volver, el chat cierra.
    state.pending_extraction = None
    state.mark("ingresos")
    state.save()
    html = client.get(CHAT).content.decode()
    session = session_of(user)
    assert session.stage == Stage.DONE and "¡Todo listo!" in html
    assert reverse("onboarding:done", args=[filling.pk]) in html
    assert assistant.after_confirm_url(user, filling) is None


def test_llenado_sin_datos_no_deja_nada_pendiente(client, user, filling):
    user.set_ai_consent(True)
    FakeProvider.queue({})
    say(client, "hola")
    assert "No encontré datos" in session_of(user).messages[-1]["texto"]
    assert get_state(filling).pending_extraction is None


def test_saltar_un_espacio_pasa_al_siguiente(client, user):
    client.force_login(user)
    for text in ("Ambos", "Dulces Ana", "pesos"):
        say(client, text)
    client.post(reverse("asistente:create"))
    negocio = Workspace.objects.get(owner=user, kind="business")
    client.post(reverse("asistente:skip"))
    session = session_of(user)
    assert session.stage == Stage.FILLING and session.queue == [str(negocio.pk)]
    assert "qué vendes" in session.messages[-1]["texto"]
    client.post(reverse("asistente:skip"))
    assert session_of(user).stage == Stage.DONE


def test_voz_sin_consentimiento(client, user):
    from django.core.files.uploadedfile import SimpleUploadedFile

    client.force_login(user)
    audio = SimpleUploadedFile("nota.webm", b"audio", content_type="audio/webm")
    response = client.post(reverse("asistente:voice"), {"audio": audio})
    assert response.status_code == 503
