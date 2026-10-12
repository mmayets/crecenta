"""Genera los íconos de la PWA en static/icons/ (requiere Pillow solo para generarlos).

Uso: uv run --with pillow python scripts/build_pwa_icons.py
Diseño: fondo verde azulado de la marca y barras ascendentes con una flecha (crecer).
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "static" / "icons"
TEAL = (15, 118, 110, 255)
WHITE = (255, 255, 255, 255)


def draw_mark(size: int, safe: float) -> Image.Image:
    """`safe`: fracción del lado reservada como margen (los íconos maskable necesitan ~10 %)."""
    scale = 4  # sobremuestreo para bordes suaves
    s = size * scale
    img = Image.new("RGBA", (s, s), TEAL)
    d = ImageDraw.Draw(img)
    inner = s * (1 - 2 * safe)
    x0 = y0 = s * safe
    bar_w = inner * 0.16
    gap = inner * 0.08
    base = y0 + inner * 0.86
    heights = [0.22, 0.34, 0.48]
    left = x0 + inner * 0.16
    for i, h in enumerate(heights):
        bx = left + i * (bar_w + gap)
        d.rounded_rectangle(
            [bx, base - inner * h, bx + bar_w, base], radius=bar_w * 0.3, fill=WHITE
        )
    # Flecha ascendente por encima de las barras, con la punta orientada según la línea.
    ax0, ay0 = x0 + inner * 0.12, y0 + inner * 0.40
    tip = (x0 + inner * 0.86, y0 + inner * 0.10)
    dx, dy = tip[0] - ax0, tip[1] - ay0
    length = (dx * dx + dy * dy) ** 0.5
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    head = inner * 0.17
    bx, by = tip[0] - ux * head, tip[1] - uy * head
    d.line([(ax0, ay0), (bx, by)], fill=WHITE, width=int(inner * 0.075))
    d.polygon(
        [
            tip,
            (bx + px * head * 0.6, by + py * head * 0.6),
            (bx - px * head * 0.6, by - py * head * 0.6),
        ],
        fill=WHITE,
    )
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    draw_mark(192, 0.12).save(OUT / "icon-192.png")
    draw_mark(512, 0.12).save(OUT / "icon-512.png")
    draw_mark(512, 0.2).save(OUT / "icon-maskable-512.png")
    draw_mark(180, 0.14).convert("RGB").save(OUT / "apple-touch-icon.png")
    draw_mark(32, 0.08).save(OUT / "favicon-32.png")
    print("íconos generados en", OUT)


if __name__ == "__main__":
    main()
