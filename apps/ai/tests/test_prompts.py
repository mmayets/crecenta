import pytest

from apps.ai.schemas import SCHEMAS, PlanNarrative
from apps.ai.services import prompts
from apps.ai.services.prompts import PromptError, render_prompt

CONTEXTS = {
    "plan_personal": {
        "moneda": "DOP",
        "estado": "viable",
        "calculado": {"estado": "viable"},
        "preferencias": {},
        "datos_faltantes": [],
    },
    "onboarding_extraccion": {"hoy": "2026-10-12", "texto": "cobro 50 mil"},
    "comprobante_ocr": {"hoy": "2026-10-12", "categorias": ["Alimentación"]},
    "registro_rapido": {"hoy": "2026-10-12", "texto": "x", "categorias": [], "cuentas": []},
}


@pytest.mark.parametrize("name", list(prompts.VERSIONS))
def test_todas_las_plantillas_se_renderizan(name):
    rendered = render_prompt(name, CONTEXTS[name])
    assert rendered.system and rendered.user
    assert "{{" not in rendered.system + rendered.user
    assert rendered.version == "v1"


def test_esquema_al_final_y_valores_json():
    rendered = render_prompt("plan_personal", CONTEXTS["plan_personal"], PlanNarrative)
    assert '"estado": "viable"' in rendered.user
    assert rendered.user.rstrip().endswith("}")
    assert "esquema" in rendered.user
    assert "viable" in rendered.system  # el estado calculado también va en las reglas


def test_falta_un_valor():
    with pytest.raises(PromptError):
        render_prompt("onboarding_extraccion", {"hoy": "2026-10-12"})


def test_plantilla_desconocida():
    with pytest.raises(PromptError):
        render_prompt("inventada", {})


def test_archivo_inexistente_o_mal_formado(tmp_path, monkeypatch):
    monkeypatch.setattr(prompts, "PROMPTS_DIR", tmp_path)
    monkeypatch.setitem(prompts.VERSIONS, "plan_personal", "v9")
    prompts._load.cache_clear()
    with pytest.raises(PromptError):
        render_prompt("plan_personal", {})
    (tmp_path / "plan_personal.v9.md").write_text("---\nversion: v9\n---\nsin secciones")
    with pytest.raises(PromptError):
        render_prompt("plan_personal", {})
    prompts._load.cache_clear()


def test_registro_de_esquemas():
    assert set(SCHEMAS) == {
        "PlanNarrative",
        "OnboardingExtraction",
        "ReceiptExtraction",
        "QuickEntry",
    }
