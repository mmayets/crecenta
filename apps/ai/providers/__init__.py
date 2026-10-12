from django.conf import settings

from .base import AIProvider, Attachment, ProviderError, ProviderResponse
from .fake import FakeProvider

__all__ = [
    "AIProvider",
    "Attachment",
    "FakeProvider",
    "ProviderError",
    "ProviderResponse",
    "get_provider",
]


def get_provider(name: str | None = None) -> AIProvider:
    """Proveedor configurado por AI_PROVIDER (gemini | openai | fake)."""
    name = name or settings.AI_PROVIDER
    if name == "gemini":
        from .gemini_provider import GeminiProvider

        return GeminiProvider(settings.GEMINI_API_KEY, settings.GEMINI_MODEL)
    if name == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(
            settings.OPENAI_API_KEY, settings.OPENAI_MODEL, settings.OPENAI_TRANSCRIBE_MODEL
        )
    if name == "fake":
        return FakeProvider()
    raise ProviderError(f"Proveedor de IA desconocido: {name}")
