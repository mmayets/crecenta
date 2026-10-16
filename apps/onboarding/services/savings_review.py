"""Revisión del ahorro en el primer espacio: ¿alcanza lo que quiere ahorrar y qué le conviene?

La app calcula todas las cifras con las respuestas del paso a paso (ingreso del mes, gastos fijos,
gastos del día a día, lo que queda libre) y arma las opciones de ahorro: lo que eligió, el método
50/30/20, «págate primero» (10 %) y lo que le alcanza. La IA solo explica los motivos y recomienda
una opción factible; sin IA (o si responde algo inválido) la explicación sale de reglas.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal
from typing import Any

from apps.accounts.models import User
from apps.ai.schemas import RevisionAhorro
from apps.ai.services.client import run_structured
from apps.core.money import ZERO, fmt

FIXED_KEYS = ("luz", "agua", "internet", "seguros", "deudas")
ESSENTIAL_KEYS = ("comida", "aseo", "transporte")
# Respuestas que cambian las cifras: si alguna cambia, la revisión se vuelve a hacer.
INPUT_KEYS = ("frecuencia", "quincenas", "monto_ingreso", "monto_ingreso_2", "vivienda",
              "monto_vivienda", *FIXED_KEYS, "otros_fijos", *ESSENTIAL_KEYS, "ahorro",
              "monto_ahorro")  # fmt: skip
SESSION_KEY = "primer_espacio_revision"
NEEDS, WANTS, SAVINGS = Decimal("0.50"), Decimal("0.30"), Decimal("0.20")
PAY_FIRST = Decimal("0.10")
WEEKS_PER_MONTH = Decimal(52) / Decimal(12)


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(value) if value not in (None, "", "variable") else ZERO
    except (ArithmeticError, TypeError, ValueError):
        return ZERO


def _fixed_amount(value: Any) -> Decimal:
    return _dec(value.get("monto")) if isinstance(value, dict) else ZERO


def monthly_income(answers: dict[str, Any]) -> Decimal:
    amount = _dec(answers.get("monto_ingreso"))
    frequency = answers.get("frecuencia")
    if frequency == "semanal":
        return (amount * WEEKS_PER_MONTH).quantize(Decimal("0.01"))
    if frequency == "quincenal":
        if answers.get("quincenas") == "distinto":
            return amount + _dec(answers.get("monto_ingreso_2"))
        return amount * 2
    return amount


def monthly_fixed(answers: dict[str, Any]) -> Decimal:
    total = _dec(answers.get("monto_vivienda"))
    total += sum((_fixed_amount(answers.get(k)) for k in FIXED_KEYS), ZERO)
    total += sum((_fixed_amount(row) for row in answers.get("otros_fijos") or []), ZERO)
    return total


def monthly_essentials(answers: dict[str, Any]) -> Decimal:
    return sum((_dec(answers.get(k)) for k in ESSENTIAL_KEYS), ZERO)


def round_down(amount: Decimal, currency: str) -> Decimal:
    """Montos redondos para sugerir: de 100 en 100 en pesos, de 10 en 10 en dólares."""
    step = Decimal(10) if currency == "USD" else Decimal(100)
    if amount <= 0:
        return ZERO
    return (amount / step).quantize(Decimal(1), rounding=ROUND_FLOOR) * step


@dataclass(frozen=True)
class Choice:
    code: str
    label: str
    hint: str
    amount: Decimal
    feasible: bool


@dataclass(frozen=True)
class Review:
    currency: str
    income: Decimal
    fixed: Decimal
    essentials: Decimal
    wanted: Decimal  # lo que eligió ahorrar (0 si dijo «ahora no»)
    choices: tuple[Choice, ...]
    recommended: str
    frequency: str = "mensual"

    @property
    def needs(self) -> Decimal:
        return self.fixed + self.essentials

    @property
    def free(self) -> Decimal:
        """Lo que queda después de las necesidades: para gustos y ahorro."""
        return self.income - self.needs

    def pct(self, amount: Decimal) -> int:
        return round(amount * 100 / self.income) if self.income > 0 else 0

    def choice(self, code: str) -> Choice | None:
        return next((c for c in self.choices if c.code == code), None)

    @property
    def status(self) -> str:
        """deficit: las necesidades no caben · no_alcanza: el ahorro elegido no cabe ·
        justo: cabe con poco margen · holgado: cabe con margen."""
        if self.free <= 0:
            return "deficit"
        if self.wanted > self.free:
            return "no_alcanza"
        return "justo" if self.free - self.wanted < self.income * PAY_FIRST else "holgado"

    def rule_503020(self) -> list[dict[str, Any]]:
        """El 50/30/20 aplicado a su ingreso, al lado de lo que hace hoy."""
        savings = self.wanted
        wants = max(self.free - savings, ZERO)
        rows = (("Necesidades", NEEDS, self.needs), ("Gustos y otros", WANTS, wants),
                ("Ahorro", SAVINGS, savings))  # fmt: skip
        return [
            {
                "nombre": name,
                "meta_pct": int(share * 100),
                "meta": fmt(self.income * share, self.currency),
                "tuyo_pct": self.pct(actual),
                "tuyo": fmt(actual, self.currency),
                "pasa": actual > self.income * share if name == "Necesidades" else None,
            }
            for name, share, actual in rows
        ]

    def figures(self) -> dict[str, Any]:
        """Cifras para la IA, ya con formato de texto."""
        money = lambda v: fmt(v, self.currency)  # noqa: E731
        return {
            "moneda": self.currency,
            "ingreso_mensual": money(self.income),
            "gastos_fijos": money(self.fixed),
            "gastos_del_dia_a_dia": money(self.essentials),
            "necesidades": f"{money(self.needs)} ({self.pct(self.needs)} % del ingreso)",
            "libre_despues_de_necesidades": money(self.free),
            "ahorro_elegido": money(self.wanted),
            "estado": self.status,
            "metodo_50_30_20": self.rule_503020(),
        }

    def options_for_ai(self) -> list[dict[str, Any]]:
        return [
            {
                "codigo": c.code,
                "opcion": c.label,
                "monto": fmt(c.amount, self.currency),
                "factible": c.feasible,
            }  # fmt: skip
            for c in self.choices
        ]

    def signature(self) -> str:
        data = json.dumps([self.figures(), self.options_for_ai()], sort_keys=True, default=str)
        return hashlib.sha256(data.encode()).hexdigest()[:16]


def build(answers: dict[str, Any], *, ignore_wanted: bool = False) -> Review:
    currency = answers.get("moneda") or "DOP"
    income = monthly_income(answers)
    fixed, essentials = monthly_fixed(answers), monthly_essentials(answers)
    free = income - fixed - essentials
    wanted = (
        ZERO
        if ignore_wanted or answers.get("ahorro") in (None, "no")
        else _dec(answers.get("monto_ahorro"))
    )
    money = lambda v: fmt(v, currency)  # noqa: E731

    def fits(amount: Decimal) -> bool:
        return ZERO < amount <= free

    choices: list[Choice] = []
    if wanted > 0:
        choices.append(Choice("mantener", f"Mantener {money(wanted)} al mes",
                              "Lo que elegiste" if fits(wanted) else "Hoy no te alcanza",
                              wanted, fits(wanted)))  # fmt: skip
    seen = {wanted}
    for code, label, hint, amount in (
        ("50_30_20", "Método 50/30/20", "El 20 % de tu ingreso", income * SAVINGS),
        ("pagate_primero", "Págate primero", "El 10 % de tu ingreso, apenas cobras",
         income * PAY_FIRST),
        ("lo_que_alcanza", "Lo que te alcanza", "La mitad de lo que te queda libre",
         free / 2 if free > 0 else ZERO),
    ):  # fmt: skip
        amount = round_down(amount, currency)
        if amount <= 0 or amount in seen:
            continue
        seen.add(amount)
        choices.append(Choice(code, f"{label}: {money(amount)} al mes",
                              hint if fits(amount) else f"{hint} · hoy no te alcanza",
                              amount, fits(amount)))  # fmt: skip
    choices.append(Choice("ahora_no", "Ahora no ahorro", "Puedes empezar después", ZERO, True))

    best = next((c for c in choices if c.code == "50_30_20" and c.feasible), None)
    keep = next((c for c in choices if c.code == "mantener" and c.feasible), None)
    if keep and (best is None or keep.amount >= best.amount):
        best = keep  # ahorra más que el 20 % y le alcanza: no hay por qué bajarlo
    best = best or next((c for c in choices if c.feasible and c.amount > 0), None)
    return Review(currency=currency, income=income, fixed=fixed, essentials=essentials,
                  wanted=wanted, choices=tuple(choices),
                  recommended=best.code if best else "ahora_no",
                  frequency=answers.get("frecuencia") or "mensual")  # fmt: skip


def suggestion(answers: dict[str, Any]) -> Choice | None:
    """Monto de ahorro mensual a sugerir apenas tiene sus gastos (antes de elegir el suyo)."""
    review = build(answers, ignore_wanted=True)
    choice = review.choice(review.recommended)
    return choice if choice and choice.amount > 0 else None


# ---------------------------------------------------------------- explicación


# ---------------------------------------------------------------- saber más del 50/30/20

# Qué entra en cada parte, con ejemplos de aquí.
BUCKETS = (
    ("Necesidades", NEEDS, "Lo que no puedes dejar de pagar: vivienda, luz, agua, internet, "
     "alimentos, aseo, transporte, seguros y cuotas de deudas."),
    ("Gustos y otros", WANTS, "Lo que te da gusto pero podrías recortar: salidas, delivery, "
     "ropa que no necesitas, suscripciones, regalos."),
    ("Ahorro", SAVINGS, "Lo que apartas apenas cobras: fondo de emergencia, metas y abonos "
     "extra a deudas."),
)  # fmt: skip
PER_PAY = {"quincenal": ("cada quincena", Decimal(2)), "semanal": ("cada semana", WEEKS_PER_MONTH)}


def method_example(review: Review) -> dict[str, Any]:
    """El 50/30/20 explicado con el ingreso de la persona: cuánto va a cada parte al mes (y en
    cada cobro), qué entra en cada una y cómo está hoy. Todo calculado por la app."""
    money = lambda v: fmt(v, review.currency)  # noqa: E731
    when, per_month = PER_PAY.get(review.frequency, ("", Decimal(1)))
    current = {row["nombre"]: row for row in review.rule_503020()}
    rows = [
        {
            "nombre": name,
            "pct": int(share * 100),
            "monto": money(review.income * share),
            "por_cobro": money(review.income * share / per_month) if when else "",
            "ejemplos": examples,
            "tuyo": current[name]["tuyo"],
            "tuyo_pct": current[name]["tuyo_pct"],
            "pasa": current[name]["pasa"],
        }
        for name, share, examples in BUCKETS
    ]
    needs, wants, savings = (review.income * s for _, s, _ in BUCKETS)
    text = [
        "El método 50/30/20 reparte lo que cobras en tres partes: la mitad para lo necesario, "
        "un 30 % para tus gustos y un 20 % para ahorrar. Así sabes cuánto puedes gastar sin "
        "dejar de ahorrar.",
        f"Con tu ingreso de {money(review.income)} al mes serían {money(needs)} para "
        f"necesidades, {money(wants)} para gustos y {money(savings)} para ahorro.",
    ]
    if when:
        text.append(
            f"Como cobras {when}, cada vez que te llegue el dinero aparta "
            f"{money(savings / per_month)} para el ahorro antes de gastar."
        )
    if review.needs > needs:
        text.append(
            f"Hoy tus necesidades suman {money(review.needs)} ({review.pct(review.needs)} %): "
            f"pasan del 50 % por {money(review.needs - needs)}. Si no puedes bajarlas, toma ese "
            "dinero de la parte de gustos y no del ahorro."
        )
    else:
        text.append(
            f"Hoy tus necesidades suman {money(review.needs)} ({review.pct(review.needs)} %): "
            "están dentro del 50 %, así que el 20 % de ahorro te queda al alcance."
        )
    return {"texto": " ".join(text), "filas": rows, "cuando": when}


def explain_by_rules(review: Review) -> RevisionAhorro:
    money = lambda v: fmt(v, review.currency)  # noqa: E731
    best = review.choice(review.recommended)
    needs_pct = review.pct(review.needs)
    reasons = [
        f"Tus necesidades (gastos fijos y del día a día) suman {money(review.needs)}, el "
        f"{needs_pct} % de tu ingreso; el método 50/30/20 sugiere no pasar del 50 % "
        f"({money(review.income * NEEDS)}).",
    ]
    if review.status == "deficit":
        message = (
            f"Tus gastos necesarios ({money(review.needs)}) ya usan todo tu ingreso del mes "
            f"({money(review.income)}), así que hoy no te queda para ahorrar. Antes de apartar "
            "dinero, revisa qué gasto fijo puedes bajar o si puedes sumar otro ingreso."
        )
        reasons.append("Ahorrar sin margen te obligaría a endeudarte para cubrir lo básico.")
        return RevisionAhorro(
            mensaje=message,
            motivos=reasons,
            metodo_recomendado="ahora_no",
            explicacion_metodo=method_example(review)["texto"],
        )
    reasons.append(
        f"Después de las necesidades te quedan {money(review.free)} para gustos y ahorro."
    )
    if review.status == "no_alcanza":
        opening = (
            f"Quieres ahorrar {money(review.wanted)}, pero después de tus necesidades te quedan "
            f"{money(review.free)}: no te alcanza sin quedarte corto."
        )
    elif review.wanted > 0:
        opening = f"¡Bien! Ahorrar {money(review.wanted)} al mes cabe en tus números."
    else:
        opening = "Todavía no elegiste cuánto ahorrar, pero tus números dejan espacio para hacerlo."
    rule = (
        f"Con el método 50/30/20, de tu ingreso de {money(review.income)} irían "
        f"{money(review.income * NEEDS)} a necesidades, {money(review.income * WANTS)} a gustos y "
        f"{money(review.income * SAVINGS)} a ahorro."
    )
    if best is None or best.amount == 0:
        advice = "Por ahora conviene esperar y empezar cuando tengas más margen."
    elif best.code == "mantener":
        advice = f"Te recomiendo mantener tus {money(best.amount)}: ahorras más que el 20 %."
    else:
        advice = f"Te recomiendo «{best.label}»."
        reasons.append(f"{best.hint}: es un monto que puedes sostener mes a mes.")
    if best and best.code == "pagate_primero":
        reasons.append("Apártalo el mismo día que cobras: lo que no ves, no lo gastas.")
    if needs_pct > 50:
        reasons.append("Si bajas un poco tus gastos fijos, podrás llegar al 20 % más adelante.")
    return RevisionAhorro(
        mensaje=f"{opening} {rule} {advice}",
        motivos=reasons[:4],
        metodo_recomendado=review.recommended,
        explicacion_metodo=method_example(review)["texto"],
    )


def explain(review: Review, user: User | None, session: Any) -> tuple[RevisionAhorro, bool]:
    """La explicación de Sophia (IA con respaldo por reglas), guardada en la sesión por cifras:
    volver a la misma pantalla no vuelve a consultar a la IA. Devuelve (explicación, de_la_ia)."""
    signature = review.signature()
    cached = session.get(SESSION_KEY) or {}
    if cached.get("firma") == signature:
        return RevisionAhorro.model_validate(cached["datos"]), bool(cached.get("ia"))
    feasible = {c.code for c in review.choices if c.feasible and c.amount > 0}

    def validator(data: RevisionAhorro) -> list[str]:
        allowed = feasible or {"ahora_no"}
        if data.metodo_recomendado not in allowed:
            return [f"metodo_recomendado debe ser uno de: {', '.join(sorted(allowed))}."]
        return []

    result = run_structured(
        workspace=None,
        user=user,
        purpose="revision_ahorro",
        prompt_name="sophia_ahorro",
        context={
            "cifras": review.figures(),
            "opciones": review.options_for_ai(),
            "ejemplo_metodo": {k: v for k, v in method_example(review).items() if k != "texto"},
        },
        schema=RevisionAhorro,
        fallback=lambda: explain_by_rules(review),
        validator=validator,
    )
    session[SESSION_KEY] = {
        "firma": signature,
        "datos": result.data.model_dump(mode="json"),
        "ia": result.from_ai,
    }
    return result.data, result.from_ai
