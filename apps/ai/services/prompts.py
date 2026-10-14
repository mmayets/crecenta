"""Plantillas de prompt versionadas en `apps/ai/prompts/<nombre>.<versión>.md`.

Formato del archivo:

    ---
    version: v1
    ---
    ## system
    …instrucciones…
    ## user
    …texto con marcadores {{ nombre }}…

Los marcadores se reemplazan por los valores del contexto (los dict/list se serializan como JSON).
El esquema JSON de salida se agrega al final del mensaje de usuario.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
# Versión vigente de cada plantilla (cambiarla aquí es el único paso para publicar una nueva).
VERSIONS = {
    "plan_personal": "v1",
    "plan_negocio": "v1",
    "onboarding_extraccion": "v1",
    "onboarding_negocio": "v1",
    "comprobante_ocr": "v1",
    "registro_rapido": "v1",
    "asistente_espacios": "v1",
    "asistente_ayuda": "v1",
    "centia_movimiento": "v1",
}
_PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


class PromptError(ValueError):
    pass


@dataclass(frozen=True)
class RenderedPrompt:
    name: str
    version: str
    system: str
    user: str


@lru_cache(maxsize=32)
def _load(name: str, version: str) -> tuple[str, str]:
    path = PROMPTS_DIR / f"{name}.{version}.md"
    if not path.exists():
        raise PromptError(f"No existe la plantilla {path.name}")
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.DOTALL)
    match = re.search(r"^## system\n(.*?)^## user\n(.*)\Z", text, flags=re.DOTALL | re.MULTILINE)
    if not match:
        raise PromptError(f"{path.name} debe tener las secciones '## system' y '## user'")
    return match.group(1).strip(), match.group(2).strip()


def _to_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=1, default=str)


def _fill(template: str, context: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in context:
            raise PromptError(f"Falta el valor '{key}' para la plantilla")
        return _to_text(context[key])

    return _PLACEHOLDER.sub(replace, template)


def render_prompt(
    name: str, context: dict[str, Any], schema: type[BaseModel] | None = None
) -> RenderedPrompt:
    if name not in VERSIONS:
        raise PromptError(f"Plantilla desconocida: {name}")
    version = VERSIONS[name]
    system, user = _load(name, version)
    user = _fill(user, context)
    if schema is not None:
        user += (
            "\n\nResponde únicamente con un objeto JSON válido que cumpla este esquema:\n"
            + json.dumps(schema.model_json_schema(), ensure_ascii=False)
        )
    return RenderedPrompt(name=name, version=version, system=_fill(system, context), user=user)
