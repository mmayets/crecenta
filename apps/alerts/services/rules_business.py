"""Reglas de alertas del negocio (funciones puras; encargo §11 y docs/fase2.md §4).

- margen_bajo_objetivo: el margen bruto del mes (o el de un producto que se vende) está bajo el
  margen objetivo del negocio.
- costos_variables_crecen: lo pagado en materiales, comisiones y entregas creció bastante más que
  las ventas, comparando los mismos días del mes anterior.
- riesgo_caja_fechas (proyección): en una fecha concreta de los próximos 30 días el efectivo no
  alcanzaría para los pagos registrados (o quedaría bajo la reserva).
- retiro_sin_cobertura: hubo retiros del propietario este mes y hoy el efectivo ya no cubre los
  compromisos registrados.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from apps.business.services.cash import CashProjection, ReserveResult
from apps.business.services.indicators import PeriodIndicators
from apps.core.money import ZERO, fmt, pct, q

from .rules_personal import AlertDraft, day_text

HUNDRED = Decimal("100")

BUSINESS_DEFAULT_PARAMS: dict[str, dict[str, Any]] = {
    "margen_bajo_objetivo": {"puntos_tolerancia": 1},
    "costos_variables_crecen": {"diferencia_pct": 10},
    "riesgo_caja_fechas": {},
    "retiro_sin_cobertura": {},
}
BUSINESS_RULE_LABELS = {
    "margen_bajo_objetivo": "Margen bajo el objetivo",
    "costos_variables_crecen": "Costos creciendo más que las ventas",
    "riesgo_caja_fechas": "Fechas con riesgo de quedarte sin efectivo",
    "retiro_sin_cobertura": "Retiros que dejan pagos sin cubrir",
}
BUSINESS_AUTO_RESOLVE = frozenset(BUSINESS_DEFAULT_PARAMS)


@dataclass(frozen=True)
class Withdrawal:
    date: datetime.date
    amount: Decimal


@dataclass(frozen=True)
class BusinessAlertContext:
    today: datetime.date
    currency: str
    month: PeriodIndicators  # mes en curso hasta hoy
    previous_same_days: PeriodIndicators  # mismos días del mes anterior
    projection: CashProjection  # con la reserva fijada
    reserve: ReserveResult
    withdrawals: list[Withdrawal]  # retiros del propietario del mes
    target_margin: Decimal | None = None  # fracción
    params: dict[str, dict[str, Any]] = field(default_factory=dict)
    enabled: frozenset[str] = frozenset(BUSINESS_DEFAULT_PARAMS)

    def param(self, code: str, name: str) -> Any:
        return {**BUSINESS_DEFAULT_PARAMS[code], **self.params.get(code, {})}[name]

    def money(self, value: Decimal) -> str:
        return fmt(value, self.currency)

    @property
    def key(self) -> str:
        return self.month.start.isoformat()


def _data(ctx: BusinessAlertContext, **extra: Any) -> dict[str, Any]:
    return {
        "periodo": [ctx.month.start.isoformat(), ctx.today.isoformat()],
        **{k: (str(v) if isinstance(v, Decimal) else v) for k, v in extra.items()},
    }


def low_margin(ctx: BusinessAlertContext) -> list[AlertDraft]:
    if ctx.target_margin is None or ctx.month.sales <= 0:
        return []
    target = q(ctx.target_margin * HUNDRED)
    tolerance = Decimal(str(ctx.param("margen_bajo_objetivo", "puntos_tolerancia")))
    margin = ctx.month.gross_margin_pct
    below = [p for p in ctx.month.by_product if p.sales > 0 and p.margin_pct < target - tolerance]
    if margin >= target - tolerance and not below:
        return []
    names = ", ".join(f"{p.name} ({p.margin_pct} %)" for p in below[:4])
    if margin < target - tolerance:
        title = "Tu margen está bajo el objetivo"
        message = (
            f"Este mes te queda {margin} % de cada venta y tu objetivo es {target} %. "
            + (f"Los productos más bajos: {names}. " if names else "")
            + "Revisa sus precios o costos en la calculadora."
        )
    else:
        title = "Algunos productos dejan menos margen del objetivo"
        message = (
            f"El margen del mes ({margin} %) está bien, pero estos productos quedan bajo el "
            f"{target} %: {names}. Revisa sus precios o costos."
        )
    return [
        AlertDraft(
            code="margen_bajo_objetivo",
            severity="alta" if margin < 0 else "media",
            title=title,
            message=message,
            dedupe_key=f"margen_bajo_objetivo:{ctx.key}",
            data_used=_data(
                ctx,
                ventas=ctx.month.sales,
                ganancia_bruta=ctx.month.gross_profit,
                margen=margin,
                margen_objetivo=target,
                productos=[p.name for p in below],
            ),
            suggested_action={"tipo": "revisar_precios", "productos": [p.ref for p in below]},
        )
    ]


def _growth(now: Decimal, before: Decimal) -> Decimal:
    return pct(now - before, before)


def variable_costs_growing(ctx: BusinessAlertContext) -> list[AlertDraft]:
    now, before = ctx.month, ctx.previous_same_days
    if before.variable_costs_paid <= 0 or before.sales <= 0:
        return []
    costs = _growth(now.variable_costs_paid, before.variable_costs_paid)
    sales = _growth(now.sales, before.sales)
    gap = Decimal(str(ctx.param("costos_variables_crecen", "diferencia_pct")))
    if costs - sales < gap:
        return []
    return [
        AlertDraft(
            code="costos_variables_crecen",
            severity="media",
            title="Tus costos crecen más rápido que tus ventas",
            message=(
                f"Comparado con los mismos días del mes pasado, lo que pagas en materiales, "
                f"comisiones y entregas subió {costs} % ({ctx.money(before.variable_costs_paid)} → "
                f"{ctx.money(now.variable_costs_paid)}), y las ventas cambiaron {sales} % "
                f"({ctx.money(before.sales)} → {ctx.money(now.sales)}). Revisa si subieron los "
                "precios de tus proveedores o si estás comprando de más."
            ),
            dedupe_key=f"costos_variables_crecen:{ctx.key}",
            data_used=_data(
                ctx,
                costos_variables=now.variable_costs_paid,
                costos_variables_antes=before.variable_costs_paid,
                ventas=now.sales,
                ventas_antes=before.sales,
            ),
            suggested_action={"tipo": "revisar_costos"},
        )
    ]


def cash_risk_dates(ctx: BusinessAlertContext) -> list[AlertDraft]:
    gaps = ctx.projection.gaps
    if not gaps:
        return []
    first = gaps[0]
    negative = first.balance < 0
    causes = ", ".join(first.causes) or "pagos registrados"
    if negative:
        message = (
            f"El {day_text(first.date)} tendrías que pagar {causes} y el efectivo no alcanza: "
            f"faltarían {ctx.money(-first.balance)}."
        )
    else:
        message = (
            f"El {day_text(first.date)}, después de pagar {causes}, el efectivo bajaría a "
            f"{ctx.money(first.balance)}, por debajo de la reserva que fijaste "
            f"({ctx.money(ctx.reserve.reserve)})."
        )
    message += " Cuenta solo los cobros con fecha; adelantar un cobro o mover un pago ayudaría."
    return [
        AlertDraft(
            code="riesgo_caja_fechas",
            severity="alta" if negative else "media",
            title=f"Riesgo de caja el {day_text(first.date)}",
            message=message,
            dedupe_key=f"riesgo_caja_fechas:{first.date.isoformat()}",
            data_used=_data(
                ctx,
                efectivo_hoy=ctx.projection.start_cash,
                fecha=first.date.isoformat(),
                saldo_proyectado=first.balance,
                conceptos=first.causes,
                fechas_en_riesgo=[g.date.isoformat() for g in gaps],
            ),
            is_projection=True,
            suggested_action={"tipo": "revisar_cobros_y_pagos"},
        )
    ]


def withdrawal_without_coverage(ctx: BusinessAlertContext) -> list[AlertDraft]:
    if not ctx.withdrawals or ctx.reserve.available >= 0:
        return []
    total = sum((w.amount for w in ctx.withdrawals), ZERO)
    last = max(ctx.withdrawals, key=lambda w: w.date)
    missing = -ctx.reserve.available
    return [
        AlertDraft(
            code="retiro_sin_cobertura",
            severity="alta",
            title="Tus retiros dejaron pagos sin cubrir",
            message=(
                f"Este mes retiraste {ctx.money(total)} del negocio (el último, el "
                f"{day_text(last.date)}). Hoy hay {ctx.money(ctx.reserve.cash)} en efectivo y "
                f"los compromisos registrados"
                + (" más la reserva" if ctx.reserve.reserve else "")
                + f" suman {ctx.money(ctx.reserve.committed + ctx.reserve.reserve)}: faltan "
                f"{ctx.money(missing)}. Evita nuevos retiros hasta cobrar o considera devolver "
                "parte como aporte."
            ),
            dedupe_key=f"retiro_sin_cobertura:{ctx.key}",
            data_used=_data(
                ctx,
                retiros=total,
                efectivo=ctx.reserve.cash,
                comprometido=ctx.reserve.committed,
                reserva=ctx.reserve.reserve,
                faltante=missing,
            ),
            suggested_action={"tipo": "pausar_retiros"},
        )
    ]


BUSINESS_RULES = {
    "margen_bajo_objetivo": low_margin,
    "costos_variables_crecen": variable_costs_growing,
    "riesgo_caja_fechas": cash_risk_dates,
    "retiro_sin_cobertura": withdrawal_without_coverage,
}


def evaluate_business(ctx: BusinessAlertContext) -> list[AlertDraft]:
    drafts: list[AlertDraft] = []
    for code, rule in BUSINESS_RULES.items():
        if code in ctx.enabled:
            drafts.extend(rule(ctx))
    return drafts
