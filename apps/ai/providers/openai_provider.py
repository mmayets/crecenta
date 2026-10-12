"""Proveedor OpenAI (SDK openai): chat con salida JSON por esquema y transcripción de audio."""

from __future__ import annotations

import base64
from typing import Any

from pydantic import BaseModel

from .base import Attachment, ProviderError, ProviderResponse


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str, model: str, transcribe_model: str, client: Any = None) -> None:
        if not api_key and client is None:
            raise ProviderError("Falta OPENAI_API_KEY")
        self.model = model
        self.transcribe_model = transcribe_model
        if client is None:
            from openai import OpenAI

            client = OpenAI(api_key=api_key, timeout=60)
        self._client = client

    @staticmethod
    def _attachment_part(a: Attachment) -> dict[str, Any]:
        encoded = base64.b64encode(a.data).decode()
        if a.mime_type == "application/pdf":
            return {
                "type": "file",
                "file": {
                    "filename": a.filename,
                    "file_data": f"data:{a.mime_type};base64,{encoded}",
                },
            }
        return {"type": "image_url", "image_url": {"url": f"data:{a.mime_type};base64,{encoded}"}}

    def generate_json(
        self,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        attachments: list[Attachment] | None = None,
        context: dict[str, Any] | None = None,
    ) -> ProviderResponse:
        content: list[dict[str, Any]] = [self._attachment_part(a) for a in attachments or []]
        content.append({"type": "text", "text": user})
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                temperature=0.2,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": content},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema.__name__,
                        "schema": schema.model_json_schema(),
                        "strict": False,
                    },
                },
            )
        except Exception as exc:
            raise ProviderError(f"OpenAI: {exc}") from exc
        text = response.choices[0].message.content if response.choices else None
        if not text:
            raise ProviderError("OpenAI devolvió una respuesta vacía")
        usage = response.usage
        return ProviderResponse(
            text=text,
            model=response.model or self.model,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )

    def transcribe(self, audio: Attachment) -> ProviderResponse:
        try:
            result = self._client.audio.transcriptions.create(
                model=self.transcribe_model,
                file=(audio.filename, audio.data, audio.mime_type),
                language="es",
            )
        except Exception as exc:
            raise ProviderError(f"OpenAI: {exc}") from exc
        text = getattr(result, "text", "")
        if not text:
            raise ProviderError("OpenAI devolvió una transcripción vacía")
        return ProviderResponse(text=text, model=self.transcribe_model)
