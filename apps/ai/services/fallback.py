"""Narrativa por reglas: se usa cuando no hay consentimiento de IA, se agotó el límite de uso, el
proveedor falla o su respuesta no pasa la validación. Solo usa cifras del plan calculado."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from apps.ai.schemas import AccionSugerida, AlternativaIA, CambioIA, PlanNarrative, Recomendacion
from apps.core.money import fmt

_MONTHS = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]  # fmt: skip


def _day(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} de {_MONTHS[d.month - 1]}"


def fallback_plan_narrative(
    computed: dict[str, Any], missing: list[dict[str, str]] | None = None, currency: str = "DOP"
) -> PlanNarrative:
    def m(value: str) -> str:
        return fmt(Decimal(value), currency)

    status = computed["estado"]
    totals = computed["totales"]
    income = m(computed["ingreso_total"])
    if status == "viable":
        summary = (
            f"Tu plan alcanza: con {income} cubres tus compromisos ({m(totals['compromiso'])}), "
            f"esenciales ({m(totals['esencial'])}) y ahorro ({m(totals['ahorro'])}), y te quedan "
            f"{m(totals['discrecional'])} para ocio y {m(totals['reserva'])} de reserva."
        )
    elif status == "ajustado":
        if Decimal(totals["reserva"]) < Decimal(computed["reserva_minima"]):
            detail = (
                f"la reserva para imprevistos es de {m(totals['reserva'])} y lo recomendable es "
                f"al menos {m(computed['reserva_minima'])}"
            )
        elif computed.get("saldo_mas_bajo") and Decimal(
            computed["saldo_mas_bajo"]["monto"]
        ) < Decimal(computed["reserva_minima"]):
            low = computed["saldo_mas_bajo"]
            detail = (
                f"el {_day(low['fecha'])} tu saldo bajaría a {m(low['monto'])}, por debajo de la "
                f"reserva recomendada ({m(computed['reserva_minima'])})"
            )
        else:
            detail = "el ocio que deseas no alcanza completo"
        summary = f"Tu plan alcanza, pero queda justo: {detail}."
    else:
        parts = []
        if Decimal(computed["faltante_total"]) > 0:
            parts.append(f"faltan {m(computed['faltante_total'])} para cubrir todo el período")
        if computed["faltantes_por_fecha"]:
            first = computed["faltantes_por_fecha"][0]
            parts.append(
                f"el {_day(first['fecha'])} te faltarían {m(first['monto'])} "
                f"({', '.join(first['conceptos'])})"
            )
        summary = "Tu plan no alcanza: " + " y ".join(parts) + ". Revisa las alternativas."

    recommendations = [
        Recomendacion(
            titulo=alt["nombre"],
            detalle=f"{alt['descripcion']} Libera {m(alt['libera'])}.",
            impacto_rd=Decimal(alt["libera"]),
            datos_usados=[c["concepto"] for c in alt["cambios"]] or ["plan del período"],
            es_proyeccion=False,
            accion_sugerida=AccionSugerida(
                tipo="aplicar_alternativa", parametros={"codigo": alt["codigo"]}
            ),
        )
        for alt in computed["alternativas"][:4]
    ]
    alternatives = [
        AlternativaIA(
            codigo=alt["codigo"],
            nombre=alt["nombre"],
            cambios=[
                CambioIA(categoria=c["concepto"], de=Decimal(c["de"]), a=Decimal(c["a"]))
                for c in alt["cambios"]
            ],
            explicacion=alt["descripcion"],
        )
        for alt in computed["alternativas"]
    ]
    missing = missing or []
    return PlanNarrative(
        resumen=summary,
        estado=status,
        recomendaciones=recommendations,
        alternativas=alternatives,
        advertencias_datos_faltantes=[item["mensaje"] for item in missing][:10],
        preguntas_para_mejorar_el_plan=[
            item["pregunta"] for item in missing if item.get("pregunta")
        ][:6],
    )
