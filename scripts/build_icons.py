"""Genera templates/icons/sprite.svg a partir de los SVG de lucide-static (licencia ISC).

Uso: python scripts/build_icons.py <ruta a lucide-static/icons>
Para agregar un ícono, súmalo a ICONS y vuelve a ejecutar.
"""

import re
import sys
from pathlib import Path

ICONS = [
    "house",
    "list",
    "plus",
    "target",
    "bell",
    "settings",
    "wallet",
    "piggy-bank",
    "receipt",
    "camera",
    "mic",
    "keyboard",
    "arrow-left-right",
    "trending-up",
    "trending-down",
    "calendar",
    "triangle-alert",
    "circle-check",
    "x",
    "trash-2",
    "pencil",
    "download",
    "log-out",
    "shield-check",
    "user",
    "chevron-right",
    "chevron-left",
    "info",
    "sparkles",
    "file-text",
    "landmark",
    "credit-card",
    "banknote",
    "briefcase",
    "refresh-cw",
    "upload",
    "wifi-off",
    "circle-help",
    "hand-coins",
    "arrow-down-left",
    "arrow-up-right",
    "calculator",
    "package",
    "shopping-cart",
    "users",
    "tag",
    "clock",
]
OUTPUT = Path(__file__).resolve().parent.parent / "templates" / "icons" / "sprite.svg"


def main(source: Path) -> None:
    symbols = []
    for name in ICONS:
        svg = (source / f"{name}.svg").read_text(encoding="utf-8")
        body = re.search(r"<svg[^>]*>(.*)</svg>", svg, re.DOTALL).group(1)
        body = " ".join(line.strip() for line in body.strip().splitlines())
        symbols.append(
            f'<symbol id="i-{name}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{body}</symbol>'
        )
    OUTPUT.write_text(
        "<!-- Íconos: Lucide v0.460.0 (ISC). Generado por scripts/build_icons.py -->\n"
        '<svg xmlns="http://www.w3.org/2000/svg" style="display:none">\n'
        + "\n".join(symbols)
        + "\n</svg>\n",
        encoding="utf-8",
    )
    print(f"{len(symbols)} íconos → {OUTPUT}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
