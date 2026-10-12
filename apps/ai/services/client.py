"""Llamada estructurada a la IA: consentimiento → límite de uso → prompt → proveedor → validación
(esquema + validador de negocio) → un reintento con los errores → respaldo por reglas.

La IA nunca guarda ni cambia datos: este módulo solo devuelve un objeto validado; quien lo llama
decide qué mostrar y todo queda como propuesta hasta que la persona lo acepte.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings
from pydantic import BaseModel, ValidationError

from apps.accounts.models import User
from apps.ai.models import AIInteraction
from apps.ai.providers import AIProvider, Attachment, ProviderError, get_provider
from apps.ai.services.prompts import render_prompt
from apps.core.ratelimit import hit
from apps.workspaces.models import Workspace

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class AIUnavailable(Exception):
    """No se pudo obtener una respuesta válida y no hay respaldo por reglas."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass
class AIResult[T: BaseModel]:
    data: T
    source: str  # "ia" | "reglas"
    outcome: str
    errors: list[str] = field(default_factory=list)
    interaction_id: Any = None

    @property
    def from_ai(self) -> bool:
        return self.source == "ia"


def parse_json(text: str) -> Any:
    """Acepta JSON puro o envuelto en un bloque ``` de markdown."""
    return json.loads(_FENCE.sub("", text.strip()))


def _validate[T: BaseModel](
    text: str, schema: type[T], validator: Callable[[T], list[str]] | None
) -> tuple[T | None, list[str]]:
    try:
        data = schema.model_validate(parse_json(text))
    except json.JSONDecodeError as exc:
        return None, [f"La respuesta no es JSON válido: {exc.msg}."]
    except ValidationError as exc:
        return None, [
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        ][:20]
    errors = validator(data) if validator else []
    return (data, errors) if not errors else (None, errors)


def ai_allowed(user: User | None) -> tuple[bool, str]:
    if user is None or not user.ai_consent:
        return False, AIInteraction.Outcome.NO_CONSENT
    if not hit(f"ai:{user.pk}", settings.AI_RATE_LIMITS):
        return False, AIInteraction.Outcome.RATE_LIMITED
    return True, ""


def run_structured[T: BaseModel](
    *,
    workspace: Workspace | None,
    user: User | None,
    purpose: str,
    prompt_name: str,
    context: dict[str, Any],
    schema: type[T],
    fallback: Callable[[], T] | None = None,
    validator: Callable[[T], list[str]] | None = None,
    attachments: list[Attachment] | None = None,
    provider: AIProvider | None = None,
) -> AIResult[T]:
    log = AIInteraction(workspace=workspace, user=user, purpose=purpose, provider="")

    def finish(result: AIResult[T]) -> AIResult[T]:
        log.outcome = result.outcome
        log.errors = result.errors
        log.save()
        result.interaction_id = log.pk
        return result

    def degrade(outcome: str, errors: list[str], message: str) -> AIResult[T]:
        if fallback is None:
            log.outcome = (
                AIInteraction.Outcome.ERROR
                if outcome == AIInteraction.Outcome.FALLBACK
                else outcome
            )
            log.errors = errors
            log.save()
            raise AIUnavailable(outcome, message)
        return finish(AIResult(data=fallback(), source="reglas", outcome=outcome, errors=errors))

    allowed, reason = ai_allowed(user)
    if not allowed:
        log.provider = "-"
        message = (
            "Activa el uso de IA en Configuración para usar esta función."
            if reason == AIInteraction.Outcome.NO_CONSENT
            else "Alcanzaste el límite de uso de IA por ahora. Intenta más tarde."
        )
        return degrade(reason, [], message)

    try:
        provider = provider or get_provider()
    except ProviderError as exc:
        log.provider = settings.AI_PROVIDER
        return degrade(AIInteraction.Outcome.FALLBACK, [str(exc)], "La IA no está disponible.")
    prompt = render_prompt(prompt_name, context, schema)
    log.provider = provider.name
    log.prompt_version = f"{prompt.name}.{prompt.version}"
    user_message = prompt.user
    errors: list[str] = []
    debug: list[dict[str, str]] = []
    started = time.monotonic()

    for attempt in range(1, MAX_ATTEMPTS + 1):
        log.attempts = attempt
        try:
            response = provider.generate_json(
                system=prompt.system,
                user=user_message,
                schema=schema,
                attachments=attachments,
                context=context,
            )
        except ProviderError as exc:
            logger.warning("IA %s falló (%s): %s", purpose, provider.name, exc)
            errors = [str(exc)]
            continue
        log.model = response.model
        log.prompt_tokens += response.prompt_tokens
        log.completion_tokens += response.completion_tokens
        if settings.AI_DEBUG_LOG:
            debug.append({"user": user_message, "response": response.text})
        data, errors = _validate(response.text, schema, validator)
        log.latency_ms = int((time.monotonic() - started) * 1000)
        log.debug_payload = debug or None
        if data is not None:
            log.schema_valid = True
            outcome = AIInteraction.Outcome.OK if attempt == 1 else AIInteraction.Outcome.RETRY_OK
            return finish(AIResult(data=data, source="ia", outcome=outcome))
        user_message = (
            prompt.user
            + "\n\nTu respuesta anterior fue rechazada por estos errores; corrígelos y responde "
            "de nuevo solo con el JSON:\n- " + "\n- ".join(errors)
        )

    log.latency_ms = int((time.monotonic() - started) * 1000)
    log.debug_payload = debug or None
    return degrade(
        AIInteraction.Outcome.FALLBACK, errors, "La IA no devolvió una respuesta válida."
    )


def transcribe(
    *,
    workspace: Workspace | None,
    user: User | None,
    audio: Attachment,
    provider: AIProvider | None = None,
) -> str:
    """Transcribe una nota de voz. Sin consentimiento o con límite agotado lanza AIUnavailable."""
    log = AIInteraction(workspace=workspace, user=user, purpose="transcripcion", provider="-")
    allowed, reason = ai_allowed(user)
    if not allowed:
        log.outcome = reason
        log.save()
        raise AIUnavailable(reason, "La transcripción de voz requiere activar el uso de IA.")
    started = time.monotonic()
    try:
        provider = provider or get_provider()
        log.provider = provider.name
        response = provider.transcribe(audio)
    except ProviderError as exc:
        log.outcome = AIInteraction.Outcome.ERROR
        log.errors = [str(exc)]
        log.save()
        raise AIUnavailable(
            AIInteraction.Outcome.ERROR, "No se pudo transcribir el audio."
        ) from exc
    log.model = response.model
    log.attempts = 1
    log.schema_valid = True
    log.latency_ms = int((time.monotonic() - started) * 1000)
    log.outcome = AIInteraction.Outcome.OK
    log.save()
    return response.text.strip()
