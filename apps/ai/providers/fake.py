"""Proveedor determinístico para tests y desarrollo sin claves (AI_PROVIDER=fake).

- En tests se le "programan" respuestas con `FakeProvider.queue(...)`; cada llamada consume una.
- Sin respuestas programadas usa un respondedor por esquema registrado con `@responder`; si no hay,
  falla con ProviderError (la capa cliente degrada entonces a reglas).
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Callable
from typing import Any, ClassVar

from pydantic import BaseModel

from .base import Attachment, ProviderError, ProviderResponse

Responder = Callable[[dict[str, Any]], BaseModel]


class FakeProvider:
    name = "fake"
    model = "fake-1"
    _queue: ClassVar[deque[str | Exception]] = deque()
    _responders: ClassVar[dict[str, Responder]] = {}
    calls: ClassVar[list[dict[str, Any]]] = []

    @classmethod
    def queue(cls, *responses: str | dict | BaseModel | Exception) -> None:
        for response in responses:
            if isinstance(response, BaseModel):
                response = response.model_dump_json()
            elif isinstance(response, dict):
                response = json.dumps(response, ensure_ascii=False, default=str)
            cls._queue.append(response)

    @classmethod
    def reset(cls) -> None:
        cls._queue.clear()
        cls.calls.clear()

    @classmethod
    def responder(cls, schema_name: str) -> Callable[[Responder], Responder]:
        def register(func: Responder) -> Responder:
            cls._responders[schema_name] = func
            return func

        return register

    def _next(self, schema_name: str, context: dict[str, Any]) -> str:
        if self._queue:
            item = self._queue.popleft()
            if isinstance(item, Exception):
                raise item
            return item
        if schema_name in self._responders:
            return self._responders[schema_name](context).model_dump_json()
        raise ProviderError(f"FakeProvider sin respuesta para {schema_name}")

    def generate_json(
        self,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        attachments: list[Attachment] | None = None,
        context: dict[str, Any] | None = None,
    ) -> ProviderResponse:
        self.calls.append({"system": system, "user": user, "schema": schema.__name__})
        text = self._next(schema.__name__, context or {})
        return ProviderResponse(
            text=text,
            model=self.model,
            prompt_tokens=len(user) // 4,
            completion_tokens=len(text) // 4,
        )

    def transcribe(self, audio: Attachment) -> ProviderResponse:
        self.calls.append({"transcribe": audio.mime_type})
        if self._queue:
            item = self._queue.popleft()
            if isinstance(item, Exception):
                raise item
            return ProviderResponse(text=item, model=self.model)
        raise ProviderError("FakeProvider sin transcripción programada")
