from decimal import Decimal

from django import template
from django.utils.html import format_html

register = template.Library()

TONOS = {
    "pendiente": "pendiente",
    "aprobado": "aprobado",
    "rechazado": "rechazado",
    "en_curso": "en-curso",
}


@register.filter
def rd(valor) -> str:
    """Monto compacto en pesos dominicanos: RD$ 412M, RD$ 1.2M, RD$ 640K."""
    if valor in (None, ""):
        return ""
    v = Decimal(valor)
    for limite, sufijo in ((Decimal(1_000_000_000), "B"), (Decimal(1_000_000), "M"), (Decimal(1_000), "K")):
        if abs(v) >= limite:
            n = v / limite
            texto = f"{n:.0f}" if abs(n) >= 100 or n == n.to_integral() else f"{n:.1f}".rstrip("0").rstrip(".")
            return f"RD$ {texto}{sufijo}"
    return f"RD$ {v:,.0f}"


@register.simple_tag
def estado(clave: str, etiqueta: str):
    return format_html('<span class="badge-estado is-{}">{}</span>', TONOS.get(clave, "neutro"), etiqueta)
