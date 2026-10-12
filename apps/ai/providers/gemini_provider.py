"""Proveedor Google Gemini (SDK google-genai). Multimodal: imágenes y PDF de comprobantes, audio."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from .base import Attachment, ProviderError, ProviderResponse


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, client: Any = None) -> None:
        if not api_key and client is None:
            raise ProviderError("Falta GEMINI_API_KEY")
        self.model = model
        if client is None:
            from google import genai

            client = genai.Client(api_key=api_key)
        self._client = client

    def _call(self, contents: list[Any], config: Any) -> ProviderResponse:
        try:
            response = self._client.models.generate_content(
                model=self.model, contents=contents, config=config
            )
        except Exception as exc:  # el SDK lanza varios tipos; todos son fallas del proveedor
            raise ProviderError(f"Gemini: {exc}") from exc
        text = getattr(response, "text", None)
        if not text:
            raise ProviderError("Gemini devolvió una respuesta vacía")
        usage = getattr(response, "usage_metadata", None)
        return ProviderResponse(
            text=text,
            model=self.model,
            prompt_tokens=getattr(usage, "prompt_token_count", 0) or 0,
            completion_tokens=getattr(usage, "candidates_token_count", 0) or 0,
        )

    def generate_json(
        self,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        attachments: list[Attachment] | None = None,
        context: dict[str, Any] | None = None,
    ) -> ProviderResponse:
        from google.genai import types

        contents: list[Any] = [
            types.Part.from_bytes(data=a.data, mime_type=a.mime_type) for a in attachments or []
        ]
        contents.append(user)
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=schema.model_json_schema(),
            temperature=0.2,
        )
        return self._call(contents, config)

    def transcribe(self, audio: Attachment) -> ProviderResponse:
        from google.genai import types

        contents = [
            types.Part.from_bytes(data=audio.data, mime_type=audio.mime_type),
            "Transcribe literalmente este audio en español. Devuelve solo el texto.",
        ]
        return self._call(contents, types.GenerateContentConfig(temperature=0))
