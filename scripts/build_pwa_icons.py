"""Genera los íconos de la PWA y las versiones livianas de los logos (Pillow solo para generarlos).

Uso: uv run --with pillow python scripts/build_pwa_icons.py

Fuentes (originales, no se modifican):
- static/logos/crecenta_logo.png: marca de la app, turquesa sobre fondo transparente.
- static/logos/sophia_logo.png: Sophia, círculo turquesa sobre un cuadrado blanco.

Salida:
- static/icons/: íconos de la PWA (marca sobre azul marino) y favicon (marca sobre transparente).
- static/logos/crecenta-marca.png: marca liviana para la interfaz.
- static/logos/sophia-avatar.png: Sophia recortado en círculo (sin el cuadrado blanco).
"""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent / "static"
ICONS = ROOT / "icons"
LOGOS = ROOT / "logos"
NAVY = (16, 34, 74, 255)


def fitted(logo: Image.Image, box: int) -> Image.Image:
    """El logo escalado para caber en un cuadrado de `box` px, sin deformarlo."""
    ratio = box / max(logo.size)
    return logo.resize((round(logo.width * ratio), round(logo.height * ratio)), Image.LANCZOS)


def icon(logo: Image.Image, size: int, safe: float, background=NAVY) -> Image.Image:
    """`safe`: fracción del lado reservada como margen (los íconos maskable necesitan ~10 %)."""
    canvas = Image.new("RGBA", (size, size), background or (0, 0, 0, 0))
    mark = fitted(logo, round(size * (1 - 2 * safe)))
    canvas.alpha_composite(mark, ((size - mark.width) // 2, (size - mark.height) // 2))
    return canvas


def sophia_circle(source: Image.Image, size: int) -> Image.Image:
    """Recorta el círculo de Sophia y deja transparente lo que queda fuera de él."""
    rgb = source.convert("RGB")
    # El círculo es lo que no es blanco; su alto da el diámetro (el borde derecho viene recortado).
    colored = rgb.point(lambda v: 255 if v < 235 else 0).convert("L")
    left, top, right, bottom = colored.getbbox()
    diameter = bottom - top
    cx, cy = left + diameter / 2, top + diameter / 2
    box = (round(cx - diameter / 2), round(cy - diameter / 2),
           round(cx + diameter / 2), round(cy + diameter / 2))  # fmt: skip
    # Lo que el original dejó fuera de la imagen se rellena con el turquesa del propio círculo.
    teal = rgb.getpixel((round(cx), top + max(4, diameter // 40)))
    square = Image.new("RGBA", (diameter, diameter), (*teal, 255))
    # Solo se copia hasta donde llega el círculo en el original; a la derecha hay un borde blanco.
    visible = source.convert("RGBA").crop((box[0], box[1], min(box[2], right - 3), box[3]))
    square.alpha_composite(visible)
    scale = 4  # sobremuestreo para un borde suave
    mask = Image.new("L", (diameter * scale, diameter * scale), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, diameter * scale - 1, diameter * scale - 1], fill=255)
    square.putalpha(mask.resize(square.size, Image.LANCZOS))
    return square.resize((size, size), Image.LANCZOS)


def main() -> None:
    ICONS.mkdir(parents=True, exist_ok=True)
    logo = Image.open(LOGOS / "crecenta_logo.png").convert("RGBA")
    icon(logo, 192, 0.16).save(ICONS / "icon-192.png", optimize=True)
    icon(logo, 512, 0.16).save(ICONS / "icon-512.png", optimize=True)
    icon(logo, 512, 0.24).save(ICONS / "icon-maskable-512.png", optimize=True)
    icon(logo, 180, 0.18).convert("RGB").save(ICONS / "apple-touch-icon.png", optimize=True)
    icon(logo, 32, 0.02, background=None).save(ICONS / "favicon-32.png", optimize=True)
    fitted(logo, 192).save(LOGOS / "crecenta-marca.png", optimize=True)

    sophia = Image.open(LOGOS / "sophia_logo.png")
    sophia_circle(sophia, 160).save(LOGOS / "sophia-avatar.png", optimize=True)
    print("Íconos y logos generados.")


if __name__ == "__main__":
    main()
