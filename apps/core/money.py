"""Utilidades de dinero.

Reglas del proyecto:
- Todo monto es `Decimal`; nunca `float` (se rechaza explícitamente).
- Los cálculos intermedios conservan la precisión; se redondea con ROUND_HALF_UP a 2 decimales
  solo al presentar o persistir (`q`).
"""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")
ZERO = Decimal("0")

CURRENCIES: dict[str, str] = {"DOP": "RD$", "USD": "US$"}
CURRENCY_CHOICES = [("DOP", "Peso dominicano (RD$)"), ("USD", "Dólar estadounidense (US$)")]


class MoneyError(ValueError):
    """Valor monetario inválido."""


def to_money(value: str | int | Decimal) -> Decimal:
    """Convierte a `Decimal` sin redondear. Rechaza `float` y `bool` para evitar imprecisiones."""
    if isinstance(value, bool | float):
        raise MoneyError("Los montos no pueden ser float; use str o Decimal.")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, str):
        cleaned = value.strip().replace(",", "").replace(" ", "")
        for symbol in CURRENCIES.values():
            cleaned = cleaned.replace(symbol, "")
        try:
            result = Decimal(cleaned)
        except InvalidOperation as exc:
            raise MoneyError(f"Monto inválido: {value!r}") from exc
    else:
        raise MoneyError(f"Tipo no soportado para monto: {type(value).__name__}")
    if not result.is_finite():
        raise MoneyError(f"Monto no finito: {value!r}")
    return result


def q(value: Decimal | int | str) -> Decimal:
    """Redondea a centavos con ROUND_HALF_UP."""
    return to_money(value).quantize(CENT, rounding=ROUND_HALF_UP)


def split_evenly(total: Decimal, parts: int) -> list[Decimal]:
    """Reparte `total` en `parts` montos de centavos que suman exactamente `total`.

    Las partes se truncan al centavo y el sobrante se agrega a la última parte.
    """
    if parts <= 0:
        raise ValueError("parts debe ser mayor que cero")
    total = q(total)
    base = (total / parts).quantize(CENT, rounding=ROUND_DOWN)
    result = [base] * parts
    result[-1] = total - base * (parts - 1)
    return result


def split_proportionally(total: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """Reparte `total` según `weights`; la suma de las partes es exactamente `q(total)`.

    Usa el método del mayor residuo para asignar los centavos sobrantes. Si todos los pesos
    son cero, reparte en partes iguales.
    """
    if not weights:
        raise ValueError("weights no puede estar vacío")
    if any(w < 0 for w in weights):
        raise ValueError("weights no puede tener valores negativos")
    total = q(total)
    weight_sum = sum(weights, ZERO)
    if weight_sum == 0:
        return split_evenly(total, len(weights))
    cents_total = int(total / CENT)
    raw = [Decimal(cents_total) * w / weight_sum for w in weights]
    floors = [int(r.to_integral_value(rounding=ROUND_DOWN)) for r in raw]
    leftover = cents_total - sum(floors)
    order = sorted(range(len(raw)), key=lambda i: (raw[i] - floors[i], -i), reverse=True)
    for i in order[:leftover]:
        floors[i] += 1
    return [Decimal(c) * CENT for c in floors]


def fmt(value: Decimal | int | str, currency: str = "DOP") -> str:
    """Formatea para mostrar: `RD$50,000.00`, `-RD$1,250.50`, `US$12.00`."""
    amount = q(value)
    symbol = CURRENCIES.get(currency, f"{currency} ")
    sign = "-" if amount < 0 else ""
    return f"{sign}{symbol}{abs(amount):,.2f}"


def pct(part: Decimal, whole: Decimal) -> Decimal:
    """Porcentaje `part/whole` con 2 decimales (0 si `whole` es 0)."""
    if whole == 0:
        return ZERO.quantize(CENT)
    return q(part * 100 / whole)


MAX_INPUT_AMOUNT = Decimal("999999999999.99")  # lo que cabe en un campo de 14 dígitos


def amount_or_zero(raw: str | None) -> Decimal:
    """Monto de un parámetro libre (avisos htmx): 0 si no es un monto válido, positivo y finito,
    o si no cabe en un campo de dinero."""
    try:
        value = to_money(raw or "0")
    except MoneyError:
        return ZERO
    if value <= 0 or value > MAX_INPUT_AMOUNT:
        return ZERO
    return value
