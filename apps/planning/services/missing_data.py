"""Qué datos faltan y cómo afectan la calidad del plan (se muestra y se envía a la IA)."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from apps.core.periods import Frequency
from apps.ledger.models import Account, Transaction
from apps.personal.services.types import PersonalInputs
from apps.workspaces.models import Workspace

_ORDER = {"alta": 0, "media": 1, "baja": 2}


@dataclass(frozen=True)
class MissingItem:
    campo: str
    mensaje: str
    impacto: str
    prioridad: str  # alta | media | baja
    pregunta: str | None = None


def compute_missing_data(inputs: PersonalInputs, *, has_balances: bool) -> list[dict[str, str]]:
    items: list[MissingItem] = []
    if not inputs.incomes:
        items.append(
            MissingItem(
                "ingresos",
                "No registraste ingresos.",
                "Sin ingresos no podemos calcular cuánto puedes gastar.",
                "alta",
                "¿Cuánto recibes neto y en qué días cobras?",
            )
        )
    elif any(i.frequency == Frequency.VARIABLE for i in inputs.incomes):
        items.append(
            MissingItem(
                "ingresos",
                "Parte de tu ingreso es variable y usamos tu estimado.",
                "Si cobras menos de lo estimado, el plan dejará de alcanzar.",
                "media",
                "¿Cuál es el mínimo que sueles recibir en un mes flojo?",
            )
        )
    if not inputs.essentials:
        items.append(
            MissingItem(
                "esenciales",
                "No indicaste cuánto gastas en comida, transporte y otros esenciales.",
                "El plan asume RD$0 para el día a día y te mostrará más dinero libre del real.",
                "alta",
                "¿Cuánto gastas al mes en comida y transporte?",
            )
        )
    if not inputs.commitments and not inputs.debts:
        items.append(
            MissingItem(
                "compromisos",
                "No registraste compromisos fijos ni deudas.",
                "Si pagas alquiler, servicios o cuotas, el plan no los está reservando.",
                "media",
                "¿Pagas alquiler, luz, internet, colegio o alguna cuota cada mes?",
            )
        )
    if not has_balances:
        items.append(
            MissingItem(
                "cuentas",
                "No registraste el saldo de tus cuentas.",
                "'Disponible para gastar' no reflejará el dinero que tienes hoy.",
                "media",
                "¿Cuánto tienes hoy en efectivo y en el banco?",
            )
        )
    if not inputs.savings:
        items.append(
            MissingItem(
                "ahorro",
                "No tienes una meta de ahorro.",
                "Todo lo que sobre se asigna a ocio y reserva.",
                "baja",
                "¿Quieres apartar algo cada mes para una meta?",
            )
        )
    if not inputs.preferences:
        items.append(
            MissingItem(
                "preferencias",
                "No marcaste qué gastos son prioritarios o reducibles.",
                "Las sugerencias no pueden ordenarse según lo que más te importa.",
                "baja",
            )
        )
    items.sort(key=lambda item: _ORDER[item.prioridad])
    return [asdict(item) for item in items]


def has_balances(workspace: Workspace) -> bool:
    """Hay saldos registrados: algún saldo inicial distinto de cero o algún movimiento."""
    return (
        Account.objects.for_workspace(workspace).exclude(opening_balance=0).exists()
        or Transaction.objects.for_workspace(workspace).exists()
    )


def missing_for_workspace(workspace: Workspace, inputs: PersonalInputs) -> list[dict[str, str]]:
    return compute_missing_data(inputs, has_balances=has_balances(workspace))
