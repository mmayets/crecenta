import json

import pytest

from apps.ai.models import AIInteraction
from apps.ai.providers import Attachment, FakeProvider, ProviderError
from apps.ai.schemas import PlanNarrative, QuickEntry
from apps.ai.services.client import AIUnavailable, parse_json, run_structured, transcribe
from apps.ai.services.fallback import fallback_plan_narrative
from apps.ai.services.guards import plan_validator

from .helpers import computed_viable

pytestmark = pytest.mark.django_db

VALID = {"resumen": "Tu plan alcanza con RD$50,000.00.", "estado": "viable"}
INVENTED = {"resumen": "Te sobran RD$4,321.00.", "estado": "viable"}


@pytest.fixture
def consent_user(user):
    user.set_ai_consent(True)
    return user


def call(user, workspace=None, fallback=True, **kw):
    computed = computed_viable()
    return run_structured(
        workspace=workspace,
        user=user,
        purpose="plan_personal",
        prompt_name="plan_personal",
        context={
            "moneda": "DOP",
            "estado": computed["estado"],
            "calculado": computed,
            "preferencias": {},
            "datos_faltantes": [],
        },
        schema=PlanNarrative,
        fallback=(lambda: fallback_plan_narrative(computed)) if fallback else None,
        validator=plan_validator(computed),
        **kw,
    )


def test_sin_consentimiento_usa_reglas_sin_llamar_a_la_ia(user, personal_ws):
    result = call(user, personal_ws)
    assert result.source == "reglas" and not result.from_ai
    assert result.outcome == "sin_consentimiento"
    assert FakeProvider.calls == []
    log = AIInteraction.objects.get(pk=result.interaction_id)
    assert (log.outcome, log.workspace, log.provider) == ("sin_consentimiento", personal_ws, "-")


def test_sin_consentimiento_y_sin_respaldo_lanza_error(user):
    with pytest.raises(AIUnavailable) as exc:
        call(user, fallback=False)
    assert exc.value.reason == "sin_consentimiento"


def test_respuesta_valida_al_primer_intento(consent_user):
    FakeProvider.queue(VALID)
    result = call(consent_user)
    assert result.from_ai and result.outcome == "ok"
    assert result.data.resumen == VALID["resumen"]
    log = AIInteraction.objects.get(pk=result.interaction_id)
    assert log.attempts == 1 and log.schema_valid
    assert log.prompt_tokens > 0 and log.completion_tokens > 0
    assert log.prompt_version == "plan_personal.v1"
    assert log.debug_payload is None  # no se guarda contenido sin AI_DEBUG_LOG
    assert str(log) == "plan_personal · fake · ok"


def test_json_invalido_se_reintenta_con_los_errores(consent_user):
    FakeProvider.queue("esto no es json", VALID)
    result = call(consent_user)
    assert result.outcome == "reintento_ok"
    assert "rechazada" in FakeProvider.calls[1]["user"]
    assert AIInteraction.objects.get(pk=result.interaction_id).attempts == 2


def test_acepta_json_en_bloque_markdown(consent_user):
    FakeProvider.queue("```json\n" + json.dumps(VALID) + "\n```")
    assert call(consent_user).outcome == "ok"
    assert parse_json('```\n{"a": 1}\n```') == {"a": 1}


def test_cifras_inventadas_dos_veces_degradan_a_reglas(consent_user):
    FakeProvider.queue(INVENTED, INVENTED)
    result = call(consent_user)
    assert result.source == "reglas" and result.outcome == "fallback"
    assert "4321.00" in result.errors[0]
    assert "4321.00" in FakeProvider.calls[1]["user"]  # el reintento informa el error
    # Lo que se muestra es la narrativa por reglas: sus cifras son las del motor.
    assert result.data.resumen.startswith("Tu plan alcanza: con RD$50,000.00")


def test_error_de_esquema_y_luego_valido(consent_user):
    FakeProvider.queue({"resumen": "x", "estado": "excelente"}, VALID)
    result = call(consent_user)
    assert result.outcome == "reintento_ok"
    assert "estado" in FakeProvider.calls[1]["user"]


def test_falla_del_proveedor_se_reintenta(consent_user):
    FakeProvider.queue(ProviderError("timeout"), VALID)
    assert call(consent_user).outcome == "reintento_ok"


def test_sin_respaldo_y_sin_respuesta_valida_lanza_error(consent_user):
    FakeProvider.queue("x", "y")
    with pytest.raises(AIUnavailable):
        call(consent_user, fallback=False)
    assert AIInteraction.objects.get().outcome == "error"


def test_limite_de_uso(consent_user, settings):
    settings.AI_RATE_LIMITS = [(1, 3600)]
    FakeProvider.queue(VALID, VALID)
    assert call(consent_user).outcome == "ok"
    assert call(consent_user).outcome == "limite"


def test_modo_depuracion_guarda_contenido(consent_user, settings):
    settings.AI_DEBUG_LOG = True
    FakeProvider.queue(VALID)
    log = AIInteraction.objects.get(pk=call(consent_user).interaction_id)
    assert log.debug_payload[0]["response"]


def test_proveedor_mal_configurado_usa_reglas(consent_user, settings):
    settings.AI_PROVIDER = "gemini"
    settings.GEMINI_API_KEY = ""
    result = call(consent_user)
    assert result.outcome == "fallback"
    assert AIInteraction.objects.get().provider == "gemini"


def test_proveedor_de_prueba_responde_plan_por_defecto(consent_user):
    result = call(consent_user)  # sin respuestas programadas: usa el respondedor por defecto
    assert result.from_ai and result.data.estado == "viable"


def test_otro_esquema_sin_respondedor_degrada(consent_user):
    with pytest.raises(AIUnavailable):
        run_structured(
            workspace=None,
            user=consent_user,
            purpose="registro_rapido",
            prompt_name="registro_rapido",
            context={"hoy": "2026-10-12", "texto": "gasté 500", "categorias": [], "cuentas": []},
            schema=QuickEntry,
        )


def test_transcripcion(consent_user, user):
    audio = Attachment(b"...", "audio/webm", "nota.webm")
    FakeProvider.queue("  gasté 500 en el colmado ")
    assert transcribe(workspace=None, user=consent_user, audio=audio) == "gasté 500 en el colmado"
    with pytest.raises(AIUnavailable):
        transcribe(workspace=None, user=consent_user, audio=audio)  # sin transcripción programada
    FakeProvider.queue(ProviderError("x"))
    with pytest.raises(AIUnavailable):
        transcribe(workspace=None, user=consent_user, audio=audio)
    assert list(AIInteraction.objects.values_list("outcome", flat=True).order_by("created_at")) == [
        "ok",
        "error",
        "error",
    ]


def test_transcripcion_sin_consentimiento(user):
    with pytest.raises(AIUnavailable) as exc:
        transcribe(workspace=None, user=user, audio=Attachment(b"", "audio/webm"))
    assert exc.value.reason == "sin_consentimiento"
