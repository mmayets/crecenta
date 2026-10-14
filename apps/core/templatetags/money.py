from decimal import Decimal, InvalidOperation

from django import template

from apps.core.money import fmt

register = template.Library()


@register.filter
def money(value, currency: str = "DOP") -> str:
    """{{ monto|money:workspace.currency }} → RD$50,000.00"""
    if value in (None, ""):
        return "—"
    try:
        return fmt(Decimal(str(value)), currency or "DOP")
    except (InvalidOperation, ValueError):
        return str(value)


@register.filter
def pct(value) -> str:
    """{{ 30|pct }} → "30.00 %" (con punto decimal, igual que los montos)."""
    if value in (None, ""):
        return "—"
    try:
        return f"{Decimal(str(value)).quantize(Decimal('0.01'))} %"
    except (InvalidOperation, ValueError):
        return str(value)


@register.filter
def miles(value) -> str:
    """Monto entero con coma de miles, sin símbolo («3,550»): para tablas con muchas columnas."""
    try:
        return f"{Decimal(str(value)):,.0f}"
    except (InvalidOperation, ValueError, TypeError):
        return ""
