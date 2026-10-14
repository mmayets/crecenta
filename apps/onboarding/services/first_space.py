"""Primer espacio con Sophia: un paso a paso visual para quien entra por primera vez.

Cada paso es una pregunta con tarjetas para elegir o una caja para escribir un valor (un monto, un
nombre). Los pasos se adaptan a lo elegido (persona, negocio o ambos; alquiler o casa propia) y la
pantalla muestra «Paso X de N» con lo que falta. Las respuestas viven en la sesión; nada se guarda
hasta «Crear mi espacio», y entonces se guarda con los mismos formularios del onboarding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.core.money import fmt
from apps.ledger.choices import CategoryGroup
from apps.ledger.services.categories import match_category
from apps.personal.models import EssentialEstimate
from apps.workspaces.models import Workspace
from apps.workspaces.services.workspaces import create_workspaces_for_usage

from .steps import get_state

SESSION_KEY = "primer_espacio"
CARDS, AMOUNT, TEXT = "tarjetas", "monto", "texto"
MAX_AMOUNT = Decimal("999999999")


@dataclass(frozen=True)
class Option:
    value: str
    label: str
    icon: str
    hint: str = ""


@dataclass(frozen=True)
class Step:
    key: str
    group: str  # sección del indicador de avance
    kind: str  # tarjetas | monto | texto
    question: str
    hint: str = ""
    options: tuple[Option, ...] = ()
    placeholder: str = ""
    skip_label: str = ""  # si se puede saltar, el texto del botón
    columns: int = 1  # tarjetas por fila en pantallas anchas


GROUPS = ("Tu espacio", "Tus ingresos", "Tus gastos", "Tu negocio", "Confirmar")
WEEKDAYS = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")

STEPS: dict[str, Step] = {
    s.key: s
    for s in (
        Step("uso", "Tu espacio", CARDS, "¡Hola! Soy Sophia. ¿Qué quieres organizar?",
             "Puedes tener tu dinero y tu negocio por separado.", (
                 Option("persona", "Mi dinero personal", "wallet", "Sueldo, gastos y ahorro"),
                 Option("negocio", "Mi negocio", "building-2", "Ventas, costos y ganancia"),
                 Option("ambos", "Los dos", "layout-dashboard", "Cada uno en su espacio"),
             ), columns=3),
        Step("moneda", "Tu espacio", CARDS, "¿En qué moneda manejas tu dinero?", "", (
            Option("DOP", "Pesos dominicanos", "banknote", "RD$"),
            Option("USD", "Dólares", "banknote", "US$"),
        ), columns=2),
        Step("frecuencia", "Tus ingresos", CARDS, "¿Cada cuánto cobras?",
             "Tu sueldo o tu ingreso principal.", (
                 Option("mensual", "Una vez al mes", "calendar"),
                 Option("quincenal", "Cada quincena", "calendar"),
                 Option("semanal", "Cada semana", "calendar"),
             ), columns=3),
        Step("monto_ingreso", "Tus ingresos", AMOUNT, "¿Cuánto recibes en cada cobro?",
             "Lo que te llega limpio, después de descuentos.", placeholder="Ej.: 35,000"),
        Step("dia_cobro", "Tus ingresos", CARDS, "¿Qué día cobras?", "", columns=7),
        Step("dinero_hoy", "Tus ingresos", AMOUNT, "¿Cuánto dinero tienes hoy?",
             "Sumando efectivo y cuentas. Lo uso para decirte cuánto puedes gastar.",
             placeholder="Ej.: 12,500", skip_label="Prefiero no decirlo"),
        Step("vivienda", "Tus gastos", CARDS, "¿Pagas vivienda cada mes?", "", (
            Option("alquiler", "Pago alquiler", "house"),
            Option("hipoteca", "Pago hipoteca", "landmark"),
            Option("no", "No pago vivienda", "circle-check", "Casa propia o familiar"),
        ), columns=3),
        Step("monto_vivienda", "Tus gastos", AMOUNT, "¿Cuánto pagas al mes?",
             placeholder="Ej.: 18,000"),
        Step("dia_vivienda", "Tus gastos", CARDS, "¿Qué día del mes lo pagas?",
             "Te aviso antes para que no se te pase.", columns=7),
        Step("comida", "Tus gastos", AMOUNT, "¿Cuánto gastas en comida al mes?",
             "Supermercado, colmado y mercado. Un aproximado está bien.",
             placeholder="Ej.: 12,000", skip_label="No lo sé todavía"),
        Step("transporte", "Tus gastos", AMOUNT, "¿Y en transporte o combustible al mes?",
             placeholder="Ej.: 4,000", skip_label="No gasto en eso"),
        Step("ahorro", "Tus gastos", CARDS, "¿Quieres ahorrar para algo?", "", (
            Option("Fondo de emergencia", "Un fondo de emergencia", "shield-check"),
            Option("Un viaje", "Un viaje", "plane"),
            Option("Comprar algo", "Comprar algo", "shopping-bag"),
            Option("no", "Ahora no", "clock"),
        ), columns=2),
        Step("monto_ahorro", "Tus gastos", AMOUNT, "¿Cuánto quieres apartar cada mes?",
             placeholder="Ej.: 3,000"),
        Step("nombre_negocio", "Tu negocio", TEXT, "¿Cómo se llama tu negocio?",
             placeholder="Ej.: Dulces Ariel"),
        Step("actividad", "Tu negocio", TEXT, "¿A qué se dedica?",
             placeholder="Ej.: repostería, salón de belleza, colmado"),
        Step("modelo", "Tu negocio", CARDS, "¿Qué vendes?", "", (
            Option("productos", "Productos", "package"),
            Option("servicios", "Servicios", "hand-coins"),
            Option("mixto", "Productos y servicios", "shopping-cart"),
        ), columns=3),
        Step("producto", "Tu negocio", TEXT, "¿Cuál es tu producto o servicio principal?",
             "Después podrás agregar los demás.", placeholder="Ej.: Bizcocho de vainilla"),
        Step("precio", "Tu negocio", AMOUNT, "¿A cuánto lo vendes?", "Sin ITBIS.",
             placeholder="Ej.: 850"),
        Step("costo", "Tu negocio", AMOUNT, "¿Cuánto te cuesta hacer o comprar cada uno?",
             "Materiales, empaque y entrega de una unidad.", placeholder="Ej.: 500",
             skip_label="No lo sé todavía"),
        Step("dinero_negocio", "Tu negocio", AMOUNT, "¿Cuánto dinero tiene hoy el negocio?",
             placeholder="Ej.: 20,000", skip_label="Prefiero no decirlo"),
        Step("gastos_negocio", "Tu negocio", AMOUNT,
             "¿Cuánto suman los gastos fijos del negocio al mes?",
             "Local, luz, internet, sueldos. Un total aproximado.", placeholder="Ej.: 15,000",
             skip_label="No tengo gastos fijos"),
    )
}  # fmt: skip
PERSONAL = ("frecuencia", "monto_ingreso", "dia_cobro", "dinero_hoy", "vivienda",
            "monto_vivienda", "dia_vivienda", "comida", "transporte", "ahorro",
            "monto_ahorro")  # fmt: skip
BUSINESS = ("nombre_negocio", "actividad", "modelo", "producto", "precio", "costo",
            "dinero_negocio", "gastos_negocio")  # fmt: skip
# Nombre corto de cada respuesta en el resumen.
LABELS = {
    "uso": "Para organizar", "moneda": "Moneda", "frecuencia": "Cada cuánto cobras",
    "monto_ingreso": "Ingreso por cobro", "dia_cobro": "Día de cobro", "dinero_hoy": "Dinero hoy",
    "vivienda": "Vivienda", "monto_vivienda": "Pago de vivienda al mes",
    "dia_vivienda": "Día de pago de la vivienda", "comida": "Comida al mes",
    "transporte": "Transporte al mes", "ahorro": "Meta de ahorro", "monto_ahorro": "Ahorro al mes",
    "nombre_negocio": "Nombre del negocio", "actividad": "A qué se dedica", "modelo": "Qué vende",
    "producto": "Producto o servicio principal", "precio": "Precio", "costo": "Costo por unidad",
    "dinero_negocio": "Dinero del negocio hoy", "gastos_negocio": "Gastos fijos al mes",
}  # fmt: skip
USAGE_KINDS = {
    "persona": {Workspace.Kind.PERSONAL},
    "negocio": {Workspace.Kind.BUSINESS},
    "ambos": {Workspace.Kind.PERSONAL, Workspace.Kind.BUSINESS},
}


# ---------------------------------------------------------------- recorrido


def owned_kinds(user: User) -> set[str]:
    return set(Workspace.objects.filter(owner=user).values_list("kind", flat=True))


def usage_options(user: User) -> tuple[Option, ...]:
    """Solo lo que todavía se puede crear: nada que incluya un tipo de espacio que ya tiene."""
    owned = owned_kinds(user)
    return tuple(o for o in STEPS["uso"].options if not USAGE_KINDS[o.value] & owned)


def path(answers: dict[str, Any]) -> list[str]:
    """Pasos que aplican según lo respondido hasta ahora (más «resumen» al final)."""
    keys = ["uso", "moneda"]
    usage = answers.get("uso")
    if usage in ("persona", "ambos"):
        for key in PERSONAL:
            pays_housing = answers.get("vivienda") in ("alquiler", "hipoteca")
            if key in ("monto_vivienda", "dia_vivienda") and not pays_housing:
                continue
            if key == "monto_ahorro" and answers.get("ahorro") in (None, "no"):
                continue
            keys.append(key)
    if usage in ("negocio", "ambos"):
        keys.extend(BUSINESS)
    if usage is None:  # aún no eligió: se estima el recorrido personal para el indicador
        keys.extend(
            k for k in PERSONAL if k not in ("monto_vivienda", "dia_vivienda", "monto_ahorro")
        )
    return [*keys, "resumen"]


def next_step(answers: dict[str, Any]) -> str:
    return next((k for k in path(answers) if k != "resumen" and k not in answers), "resumen")


def previous_step(answers: dict[str, Any], current: str) -> str | None:
    keys = path(answers)
    if current not in keys:
        return None
    index = keys.index(current)
    return keys[index - 1] if index else None


def progress(answers: dict[str, Any], current: str) -> dict[str, Any]:
    """Para el indicador: número de paso, total, lo que falta y en qué sección va."""
    keys = path(answers)
    number = keys.index(current) + 1 if current in keys else len(keys)
    groups_in_path = [g for g in GROUPS if g == "Confirmar" or any(
        STEPS[k].group == g for k in keys if k != "resumen")]  # fmt: skip
    group = "Confirmar" if current == "resumen" else STEPS[current].group
    return {
        "number": number,
        "total": len(keys),
        "left": len(keys) - number,
        "percent": round((number - 1) * 100 / max(len(keys) - 1, 1)),
        "groups": [
            {
                "name": g,
                "done": groups_in_path.index(g) < groups_in_path.index(group),
                "current": g == group,
            }
            for g in groups_in_path
        ],
    }


def options_for(step: Step, answers: dict[str, Any], user: User) -> tuple[Option, ...]:
    if step.key == "uso":
        return usage_options(user)
    if step.key == "dia_vivienda":
        return tuple(Option(str(d), str(d), "") for d in range(1, 32))
    if step.key != "dia_cobro":
        return step.options
    frequency = answers.get("frecuencia")
    if frequency == "semanal":
        return tuple(Option(str(i), day, "calendar") for i, day in enumerate(WEEKDAYS))
    if frequency == "quincenal":
        return (
            Option("15,30", "El 15 y el 30", "calendar", "Fin de mes"),
            Option("1,15", "El 1 y el 15", "calendar"),
            Option("14,28", "El 14 y el 28", "calendar"),
        )
    return tuple(Option(str(d), str(d), "") for d in range(1, 32))


def columns_for(step: Step, answers: dict[str, Any]) -> int:
    if step.key == "dia_vivienda":
        return 7
    if step.key == "dia_cobro":
        return {"semanal": 1, "quincenal": 1}.get(answers.get("frecuencia") or "", 7)
    return step.columns


def question_for(step: Step, answers: dict[str, Any]) -> str:
    if step.key == "monto_ingreso":
        each = {"quincenal": "cada quincena", "semanal": "cada semana"}.get(
            answers.get("frecuencia") or "", "cada mes"
        )
        return f"¿Cuánto recibes {each}?"
    if step.key == "dia_cobro" and answers.get("frecuencia") == "quincenal":
        return "¿Qué días cobras?"
    if step.key == "monto_vivienda":
        return f"¿Cuánto pagas de {answers.get('vivienda', 'vivienda')} al mes?"
    if step.key == "monto_ahorro":
        return f"¿Cuánto quieres apartar cada mes para «{answers.get('ahorro')}»?"
    return step.question


# ---------------------------------------------------------------- respuestas


def parse_amount(raw: str) -> Decimal | None:
    """Acepta «35,000», «35.000», «RD$ 1,250.50» o «35 mil»."""
    text = raw.strip().lower().replace("rd$", "").replace("us$", "").replace("$", "")
    thousands = bool(re.search(r"\bmil\b", text))
    text = re.sub(r"[^\d.,]", "", text)
    if not text:
        return None
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", text):
        text = re.sub(r"[.,]", "", text)
    elif re.fullmatch(r"\d{1,3}(,\d{3})+\.\d{1,2}", text):
        text = text.replace(",", "")
    else:
        text = text.replace(",", ".")
    try:
        value = Decimal(text) * (1000 if thousands else 1)
    except InvalidOperation:
        return None
    return value.quantize(Decimal("0.01")) if 0 < value <= MAX_AMOUNT else None


def clean_answer(
    step: Step, raw: str, answers: dict[str, Any], user: User
) -> tuple[Any, str | None]:
    """Valida lo enviado en un paso: (valor, error)."""
    raw = (raw or "").strip()
    if step.kind == CARDS:
        valid = {o.value for o in options_for(step, answers, user)}
        return (raw, None) if raw in valid else (None, "Elige una de las opciones.")
    if step.kind == AMOUNT:
        value = parse_amount(raw)
        if value is None:
            return None, "Escribe un monto mayor que cero, por ejemplo 15,000."
        return str(value), None
    text = " ".join(raw.split())[:80]
    return (text, None) if len(text) >= 2 else (None, "Escríbelo en pocas palabras.")


def save_answer(answers: dict[str, Any], key: str, value: Any) -> None:
    """Guarda y borra lo que dejó de aplicar (p. ej., el monto de alquiler si ya no paga)."""
    answers[key] = value
    if key == "frecuencia":
        answers.pop("dia_cobro", None)
    valid = set(path(answers))
    for stale in [k for k in answers if k not in valid]:
        del answers[stale]


def display(answers: dict[str, Any], key: str, currency: str, user: User) -> str:
    """La respuesta tal como se muestra en el resumen."""
    value = answers.get(key)
    if value is None:
        return "—"
    step = STEPS[key]
    if value == "":
        return step.skip_label or "—"
    if step.kind == AMOUNT:
        return fmt(Decimal(value), currency)
    if step.kind == CARDS:
        option = next((o for o in options_for(step, answers, user) if o.value == value), None)
        if key == "dia_vivienda" or (key == "dia_cobro" and answers.get("frecuencia") == "mensual"):
            return f"Día {value}"
        return option.label if option else value
    return value


# ---------------------------------------------------------------- crear


class CreationError(Exception):
    def __init__(self, step: str, message: str) -> None:
        super().__init__(message)
        self.step = step


def _currency(answers: dict[str, Any]) -> str:
    return answers.get("moneda") or "DOP"


def _require(form: Any, step: str) -> Any:
    if not form.is_valid():
        errors = "; ".join(" ".join(e) for e in form.errors.values())
        raise CreationError(step, errors or "Revisa este dato.")
    return form.save()


def _amount(answers: dict[str, Any], key: str) -> Decimal | None:
    value = answers.get(key)
    return Decimal(value) if value else None


def _fill_personal(workspace: Workspace, answers: dict[str, Any]) -> None:
    from apps.onboarding.business_views import _save_cash
    from apps.onboarding.forms import CommitmentForm, IncomeForm, SavingsGoalForm

    state = get_state(workspace)
    frequency = answers["frecuencia"]
    days = answers["dia_cobro"].split(",")
    income = {"name": "Mi ingreso principal", "net_amount": answers["monto_ingreso"],
              "frequency": frequency}  # fmt: skip
    if frequency == "semanal":
        income["dia_semana"] = days[0]
    else:
        income["dia_1"] = days[0]
        if len(days) > 1:
            income["dia_2"] = days[1]
    _require(IncomeForm(income, workspace=workspace), "monto_ingreso")
    state.mark("ingresos")

    cash = _amount(answers, "dinero_hoy")
    if cash:
        _save_cash(workspace, cash)
        state.mark("cuentas")

    if answers["vivienda"] in ("alquiler", "hipoteca"):
        category = match_category(workspace, "Alquiler o hipoteca", CategoryGroup.COMPROMISO_FIJO)
        _require(
            CommitmentForm(
                {
                    "name": answers["vivienda"].capitalize(),
                    "category": category.pk if category else "",
                    "amount": answers["monto_vivienda"],
                    "frequency": "mensual",
                    "due_day": answers["dia_vivienda"],
                    "is_fixed": "on",
                },
                workspace=workspace,
            ),
            "monto_vivienda",
        )
    state.mark("compromisos")  # «no pago vivienda» también es una respuesta

    essentials = (("comida", "Alimentación"), ("transporte", "Transporte y combustible"))
    for key, name in essentials:
        amount = _amount(answers, key)
        category = match_category(workspace, name, CategoryGroup.ESENCIAL_VARIABLE)
        if amount and category:
            EssentialEstimate.objects.update_or_create(
                workspace=workspace, category=category, defaults={"amount": amount}
            )
    if answers.get("comida") or answers.get("transporte"):
        state.mark("esenciales")

    if answers["ahorro"] == "no":
        state.mark("ahorro", skipped=True)
    else:
        _require(
            SavingsGoalForm(
                {
                    "purpose": answers["ahorro"],
                    "contribution_amount": answers["monto_ahorro"],
                    "contribution_frequency": "mensual",
                    "daily_mode": "todos_los_dias",
                },
                workspace=workspace,
            ),
            "monto_ahorro",
        )
        state.mark("ahorro")
    state.save()


def _fill_business(workspace: Workspace, answers: dict[str, Any]) -> None:
    from apps.onboarding.business_forms import ExpenseForm, ProductForm, ProfileForm
    from apps.onboarding.business_views import _save_cash

    state = get_state(workspace)
    _require(
        ProfileForm(
            {"activity": answers["actividad"], "model": answers["modelo"]}, workspace=workspace
        ),
        "actividad",
    )
    state.mark("perfil")
    product = {"name": answers["producto"], "price": answers["precio"],
               "unit_cost": answers.get("costo") or "0"}  # fmt: skip
    if answers["modelo"] == "servicios":
        product["is_service"] = "on"
    _require(ProductForm(product, workspace=workspace), "producto")
    state.mark("productos")
    cash = _amount(answers, "dinero_negocio")
    if cash:
        _save_cash(workspace, cash)
        state.mark("efectivo")
    expenses = _amount(answers, "gastos_negocio")
    if expenses:
        _require(
            ExpenseForm(
                {"name": "Gastos fijos del negocio", "amount": str(expenses),
                 "frequency": "mensual"},
                workspace=workspace,
            ),
            "gastos_negocio",
        )  # fmt: skip
        state.mark("gastos")
    elif answers.get("gastos_negocio") == "":
        state.mark("gastos", skipped=True)
    state.save()


@transaction.atomic
def create(user: User, answers: dict[str, Any]) -> list[Workspace]:
    """Crea los espacios y guarda lo respondido. Si algo no valida, no queda nada a medias."""
    missing = next_step(answers)
    if missing != "resumen":
        raise CreationError(missing, "Falta responder este paso.")
    created = create_workspaces_for_usage(
        user,
        answers["uso"],
        currency=_currency(answers),
        business_name=answers.get("nombre_negocio"),
    )
    if not created:
        raise CreationError("uso", "Ya tienes ese espacio.")
    for workspace in created:
        if workspace.is_business:
            _fill_business(workspace, answers)
        else:
            _fill_personal(workspace, answers)
        state = get_state(workspace)
        state.finished_at = timezone.now()
        state.save()
    return created
