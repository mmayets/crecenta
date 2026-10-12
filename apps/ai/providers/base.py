"""Interfaz común de los proveedores de IA.

Los proveedores solo transportan: reciben instrucciones y devuelven texto (JSON). Validar,
reintentar y degradar a reglas es responsabilidad de `apps.ai.services.client`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel


class ProviderError(Exception):
    """Falla del proveedor (red, cuota, credenciales, respuesta vacía)."""


@dataclass(frozen=True)
class Attachment:
    data: bytes
    mime_type: str
    filename: str = "archivo"


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


class AIProvider(Protocol):
    name: str

    def generate_json(
        self,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        attachments: list[Attachment] | None = None,
        context: dict[str, Any] | None = None,
    ) -> ProviderResponse: ...

    def transcribe(self, audio: Attachment) -> ProviderResponse: ...
