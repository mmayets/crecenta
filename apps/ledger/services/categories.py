"""Reconocimiento de categorías y cuentas por nombre (texto, voz, comprobantes, onboarding)."""

from __future__ import annotations

import unicodedata

from apps.ledger.models import Account, Category
from apps.workspaces.models import Workspace

# Palabras habituales → categoría del sistema.
SYNONYMS = {
    "comida": "Alimentación", "supermercado": "Alimentación", "colmado": "Alimentación",
    "compra": "Alimentación", "gasolina": "Transporte y combustible",
    "combustible": "Transporte y combustible", "pasaje": "Transporte y combustible",
    "guagua": "Transporte y combustible", "transporte": "Transporte y combustible",
    "taxi": "Transporte y combustible", "uber": "Transporte y combustible",
    "farmacia": "Salud y farmacia", "medicina": "Salud y farmacia",
    "medicinas": "Salud y farmacia", "limpieza": "Aseo y hogar", "aseo": "Aseo y hogar",
    "luz": "Electricidad", "electricidad": "Electricidad", "renta": "Alquiler o hipoteca",
    "alquiler": "Alquiler o hipoteca", "telefono": "Internet y teléfono",
    "internet": "Internet y teléfono", "colegio": "Educación", "universidad": "Educación",
    "restaurante": "Restaurantes y delivery", "delivery": "Restaurantes y delivery",
    "cine": "Ocio y salidas", "salida": "Ocio y salidas", "sueldo": "Salario",
    "salario": "Salario", "quincena": "Salario",
}  # fmt: skip


def normalize(text: str | None) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return " ".join("".join(c if c.isalnum() else " " for c in text.lower()).split())


def match_category(workspace: Workspace, name: str | None, *groups: str) -> Category | None:
    """Categoría por nombre exacto, sinónimo o coincidencia parcial (dentro de los grupos dados)."""
    target = normalize(name)
    if not target:
        return None
    target = normalize(SYNONYMS.get(target, target))
    categories = Category.objects.for_workspace(workspace).filter(is_archived=False)
    if groups:
        categories = categories.filter(group__in=groups)
    items = list(categories)
    exact = next((c for c in items if normalize(c.name) == target), None)
    return exact or next(
        (c for c in items if target in normalize(c.name) or normalize(c.name) in target), None
    )


def match_account(workspace: Workspace, name: str | None) -> Account | None:
    target = normalize(name)
    if not target:
        return None
    accounts = list(Account.objects.for_workspace(workspace).filter(is_archived=False))
    return next((a for a in accounts if normalize(a.name) == target), None) or next(
        (a for a in accounts if target in normalize(a.name) or normalize(a.name) in target), None
    )
