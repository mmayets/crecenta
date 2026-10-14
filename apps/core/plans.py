"""Planes de precios que muestra la página de inicio.

Por ahora son informativos: no hay pasarela de pago ni cuotas por plan (todas las cuentas usan
los límites de IA generales de `AI_RATE_LIMITS`).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Plan:
    key: str
    name: str
    monthly: Decimal
    yearly: Decimal
    summary: str
    features: tuple[str, ...]
    highlighted: bool = False

    @property
    def yearly_saving(self) -> Decimal:
        return self.monthly * 12 - self.yearly

    @property
    def free(self) -> bool:
        return self.monthly == 0

    # Precios como se escriben en RD: «RD$1,990» (coma de miles, sin centavos).
    @property
    def monthly_label(self) -> str:
        return f"RD${self.monthly:,.0f}"

    @property
    def yearly_label(self) -> str:
        return f"RD${self.yearly:,.0f}"

    @property
    def yearly_saving_label(self) -> str:
        return f"RD${self.yearly_saving:,.0f}"


PLANS = (
    Plan(
        "gratis", "Gratis", Decimal("0"), Decimal("0"),
        "Para empezar a ordenar tus finanzas personales.",
        ("Espacio de finanzas personales", "Plan del mes y «disponible para gastar»",
         "Alertas y recomendaciones de Sophia", "20 usos de IA al mes"),
    ),
    Plan(
        "personal", "Personal", Decimal("199"), Decimal("1990"),
        "Para quien quiere que Sophia le ayude todos los días.",
        ("Todo lo del plan Gratis", "IA con cuota amplia",
         "Comprobantes con foto (lectura automática)", "Registro por voz"),
        highlighted=True,
    ),
    Plan(
        "negocio", "Negocio", Decimal("449"), Decimal("4490"),
        "Para tu dinero y tu emprendimiento, cada uno en su espacio.",
        ("Todo lo del plan Personal", "Espacio de negocio: ventas, costos y ganancia",
         "Equipo con roles (vendedores)", "Recetas e inventario",
         "Archivos de apoyo 606 y 607 (DGII)"),
    ),
)  # fmt: skip
