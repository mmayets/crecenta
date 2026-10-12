from types import SimpleNamespace

import pytest

from apps.ai.providers import FakeProvider, ProviderError, get_provider
from apps.ai.providers.base import Attachment
from apps.ai.providers.gemini_provider import GeminiProvider
from apps.ai.providers.openai_provider import OpenAIProvider
from apps.ai.schemas import QuickEntry

IMG = Attachment(b"\x89PNG", "image/png", "foto.png")
PDF = Attachment(b"%PDF", "application/pdf", "factura.pdf")


class Recorder:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.kwargs = result, error, None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.result


def gemini(result=None, error=None):
    rec = Recorder(result, error)
    client = SimpleNamespace(models=SimpleNamespace(generate_content=rec))
    return GeminiProvider("", "gemini-test", client=client), rec


class TestGemini:
    def test_json_con_adjuntos_y_esquema(self):
        usage = SimpleNamespace(prompt_token_count=11, candidates_token_count=7)
        provider, rec = gemini(SimpleNamespace(text='{"a": 1}', usage_metadata=usage))
        response = provider.generate_json(
            system="s", user="u", schema=QuickEntry, attachments=[IMG]
        )
        assert (response.text, response.prompt_tokens, response.completion_tokens) == (
            '{"a": 1}',
            11,
            7,
        )
        config = rec.kwargs["config"]
        assert config.system_instruction == "s"
        assert config.response_mime_type == "application/json"
        assert config.response_json_schema["title"] == "QuickEntry"
        assert len(rec.kwargs["contents"]) == 2 and rec.kwargs["contents"][-1] == "u"

    def test_errores(self):
        provider, _ = gemini(error=RuntimeError("cuota"))
        with pytest.raises(ProviderError, match="cuota"):
            provider.generate_json(system="s", user="u", schema=QuickEntry)
        provider, _ = gemini(SimpleNamespace(text="", usage_metadata=None))
        with pytest.raises(ProviderError):
            provider.generate_json(system="s", user="u", schema=QuickEntry)
        with pytest.raises(ProviderError):
            GeminiProvider("", "m")

    def test_transcripcion(self):
        provider, rec = gemini(SimpleNamespace(text="hola", usage_metadata=None))
        assert provider.transcribe(Attachment(b"a", "audio/webm")).text == "hola"
        assert "Transcribe" in rec.kwargs["contents"][1]

    def test_cliente_real_se_construye_con_clave(self):
        assert GeminiProvider("clave-de-prueba", "m").model == "m"


def openai_client(chat=None, chat_error=None, audio=None, audio_error=None):
    chat_rec, audio_rec = Recorder(chat, chat_error), Recorder(audio, audio_error)
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=chat_rec)),
        audio=SimpleNamespace(transcriptions=SimpleNamespace(create=audio_rec)),
    )
    return OpenAIProvider("", "gpt-test", "whisper-test", client=client), chat_rec, audio_rec


def chat_response(text):
    message = SimpleNamespace(content=text)
    usage = SimpleNamespace(prompt_tokens=20, completion_tokens=5)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage, model="gpt-x")


class TestOpenAI:
    def test_json_con_imagen_y_pdf(self):
        provider, rec, _ = openai_client(chat_response('{"ok": true}'))
        response = provider.generate_json(
            system="s", user="u", schema=QuickEntry, attachments=[IMG, PDF]
        )
        assert (response.text, response.model, response.prompt_tokens) == (
            '{"ok": true}',
            "gpt-x",
            20,
        )
        content = rec.kwargs["messages"][1]["content"]
        assert content[0]["type"] == "image_url"
        assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")
        assert content[1]["type"] == "file" and content[1]["file"]["filename"] == "factura.pdf"
        assert content[2] == {"type": "text", "text": "u"}
        assert rec.kwargs["response_format"]["json_schema"]["name"] == "QuickEntry"

    def test_errores(self):
        provider, _, _ = openai_client(chat_error=RuntimeError("401"))
        with pytest.raises(ProviderError, match="401"):
            provider.generate_json(system="s", user="u", schema=QuickEntry)
        provider, _, _ = openai_client(SimpleNamespace(choices=[], usage=None, model=None))
        with pytest.raises(ProviderError):
            provider.generate_json(system="s", user="u", schema=QuickEntry)
        with pytest.raises(ProviderError):
            OpenAIProvider("", "m", "t")

    def test_transcripcion(self):
        provider, _, rec = openai_client(audio=SimpleNamespace(text="gasté 300"))
        assert provider.transcribe(Attachment(b"a", "audio/webm", "n.webm")).text == "gasté 300"
        assert rec.kwargs["language"] == "es"
        provider, _, _ = openai_client(audio=SimpleNamespace(text=""))
        with pytest.raises(ProviderError):
            provider.transcribe(Attachment(b"a", "audio/webm"))
        provider, _, _ = openai_client(audio_error=RuntimeError("x"))
        with pytest.raises(ProviderError):
            provider.transcribe(Attachment(b"a", "audio/webm"))

    def test_cliente_real_se_construye_con_clave(self):
        assert OpenAIProvider("clave-de-prueba", "m", "t").model == "m"


def test_seleccion_de_proveedor(settings):
    assert isinstance(get_provider("fake"), FakeProvider)
    settings.GEMINI_API_KEY = "x"
    settings.OPENAI_API_KEY = "x"
    assert get_provider("gemini").name == "gemini"
    assert get_provider("openai").name == "openai"
    with pytest.raises(ProviderError):
        get_provider("otro")


def test_proveedor_de_prueba():
    FakeProvider.queue(QuickEntry(tipo="gasto", monto=5), RuntimeError("boom"))
    fake = FakeProvider()
    assert '"tipo":"gasto"' in fake.generate_json(system="", user="", schema=QuickEntry).text
    with pytest.raises(RuntimeError):
        fake.generate_json(system="", user="", schema=QuickEntry)
    with pytest.raises(ProviderError):
        fake.generate_json(system="", user="", schema=QuickEntry)
    FakeProvider.queue(RuntimeError("audio"))
    with pytest.raises(RuntimeError):
        fake.transcribe(IMG)
