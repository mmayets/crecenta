"""Verificación de cifras: ninguna cifra mostrada por la IA puede diferir de las del motor.

Se aceptan en la narrativa:
- cualquier monto presente en el plan calculado (incluidos los de las alternativas y los supuestos);
- la diferencia entre dos de esos montos (p. ej. "bajar de RD$7,000.00 a RD$5,000.00 libera
  RD$2,000.00");
- porcentajes que aparezcan en el plan calculado.

Se consideran montos en el texto (docs/decisiones.md §15, §56): los precedidos por RD$/US$/$, los
seguidos de "pesos"/"dólares", los que usan separador de miles (12,345) y los que tienen 2
decimales. Números sueltos sin formato (días, años, cantidades) no se tratan como dinero.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator
from decimal import Decimal, InvalidOperation
from typing import Any

from apps.ai.schemas import PlanNarrative
from apps.core.money import q

_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?"
_CURRENCY = re.compile(rf"(?:RD\$|US\$|\$)\s?({_NUM})")
_WORDS = re.compile(rf"({_NUM})\s*(?:pesos|dólares|dolares)\b", re.IGNORECASE)
_THOUSANDS = re.compile(r"(?<![\w.,$])(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?)(?![\d,])")
_TWO_DECIMALS = re.compile(r"(?<![\w.,$])(\d+\.\d{2})(?![\d.])")
_PERCENT = re.compile(r"(\d+(?:[.,]\d+)?)\s?%")
_PLAIN_AMOUNT = re.compile(r"^-?\d+\.\d{2}$")


def _dec(raw: str) -> Decimal | None:
    try:
        return q(Decimal(raw.replace(",", "")))
    except InvalidOperation:  # pragma: no cover - el regex solo deja pasar números
        return None


def extract_amounts(text: str) -> list[Decimal]:
    """Montos de dinero mencionados en un texto libre."""
    found: list[Decimal] = []
    rest = text
    for pattern in (_CURRENCY, _WORDS):
        for match in pattern.finditer(rest):
            value = _dec(match.group(1))
            if value is not None:
                found.append(value)
        rest = pattern.sub(" ", rest)
    rest = _PERCENT.sub(" ", rest)
    for pattern in (_THOUSANDS, _TWO_DECIMALS):
        for match in pattern.finditer(rest):
            value = _dec(match.group(1))
            if value is not None:
                found.append(value)
        rest = pattern.sub(" ", rest)
    return found


def extract_percents(text: str) -> list[Decimal]:
    return [Decimal(m.group(1).replace(",", ".")) for m in _PERCENT.finditer(text)]


def _walk(value: Any) -> Iterator[Any]:
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _walk(item)
    else:
        yield value


def allowed_amounts(computed: dict[str, Any]) -> set[Decimal]:
    """Montos del plan calculado y sus diferencias (siempre en valor absoluto)."""
    base: set[Decimal] = set()
    for value in _walk(computed):
        if isinstance(value, Decimal):
            base.add(q(value))
        elif isinstance(value, str):
            if _PLAIN_AMOUNT.match(value):
                base.add(q(Decimal(value)))
            else:
                base.update(extract_amounts(value))
    base = {abs(v) for v in base}
    values = sorted(base)
    differences = {b - a for i, a in enumerate(values) for b in values[i + 1 :]}
    return base | differences | {Decimal("0.00")}


def allowed_percents(computed: dict[str, Any]) -> set[Decimal]:
    found: set[Decimal] = set()
    for value in _walk(computed):
        if isinstance(value, str):
            found.update(extract_percents(value))
    return found


def _texts(narrative: PlanNarrative) -> Iterable[tuple[str, str]]:
    yield "resumen", narrative.resumen
    for i, rec in enumerate(narrative.recomendaciones):
        yield f"recomendaciones.{i}.titulo", rec.titulo
        yield f"recomendaciones.{i}.detalle", rec.detalle
    for i, alt in enumerate(narrative.alternativas):
        yield f"alternativas.{i}.nombre", alt.nombre
        yield f"alternativas.{i}.explicacion", alt.explicacion
    for i, text in enumerate(narrative.advertencias_datos_faltantes):
        yield f"advertencias_datos_faltantes.{i}", text
    for i, text in enumerate(narrative.preguntas_para_mejorar_el_plan):
        yield f"preguntas_para_mejorar_el_plan.{i}", text


def verify_narrative(narrative: PlanNarrative, computed: dict[str, Any]) -> list[str]:
    """Lista de errores (vacía si todas las cifras coinciden con el motor)."""
    errors: list[str] = []
    allowed = allowed_amounts(computed)
    percents = allowed_percents(computed)

    if narrative.estado != computed.get("estado"):
        errors.append(
            f"estado: dijiste '{narrative.estado}' pero el calculado es '{computed.get('estado')}'."
        )
    for path, text in _texts(narrative):
        for amount in extract_amounts(text):
            if amount not in allowed:
                errors.append(f"{path}: el monto {amount} no está en el plan calculado.")
        for percent in extract_percents(text):
            if percent not in percents:
                errors.append(f"{path}: el porcentaje {percent}% no está en el plan calculado.")
    for i, rec in enumerate(narrative.recomendaciones):
        if q(rec.impacto_rd) not in allowed:
            errors.append(f"recomendaciones.{i}.impacto_rd: {rec.impacto_rd} no está calculado.")

    engine_alts = {a["codigo"]: a for a in computed.get("alternativas", [])}
    for i, alt in enumerate(narrative.alternativas):
        if alt.codigo and alt.codigo not in engine_alts:
            errors.append(
                f"alternativas.{i}.codigo: '{alt.codigo}' no es una alternativa calculada."
            )
        if not alt.codigo and alt.cambios:
            errors.append(f"alternativas.{i}: indica el 'codigo' de la alternativa calculada.")
        for j, change in enumerate(alt.cambios):
            for field in ("de", "a"):
                value = q(getattr(change, field))
                if value not in allowed:
                    errors.append(
                        f"alternativas.{i}.cambios.{j}.{field}: {value} no está calculado."
                    )
    return errors


def plan_validator(computed: dict[str, Any]) -> Callable[[PlanNarrative], list[str]]:
    """Validador para `run_structured`: rechaza narrativas con cifras que el motor no calculó."""

    def validate(narrative: PlanNarrative) -> list[str]:
        return verify_narrative(narrative, computed)

    return validate
