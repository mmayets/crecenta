from django import template
from django.utils.html import format_html

register = template.Library()


@register.simple_tag
def icon(name: str, css: str = "h-5 w-5", label: str = "") -> str:
    """{% icon "wallet" "h-6 w-6" %} → SVG del sprite. Decorativo salvo que se pase `label`."""
    if label:
        return format_html(
            '<svg class="{}" role="img" aria-label="{}"><use href="#i-{}"></use></svg>',
            css,
            label,
            name,
        )
    return format_html(
        '<svg class="{}" aria-hidden="true" focusable="false"><use href="#i-{}"></use></svg>',
        css,
        name,
    )
