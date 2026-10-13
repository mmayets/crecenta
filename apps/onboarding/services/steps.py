"""Pasos del onboarding (personal y de negocio) y completitud del perfil.

Los pasos mínimos (ingresos, compromisos, esenciales) bastan para un primer plan; el resto se puede
omitir y completar después. La completitud indica qué falta y cómo afecta la calidad del plan.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.business.models import BusinessGoal, BusinessProfile, OperatingExpense, Product
from apps.ledger.models import Account, Transaction
from apps.onboarding.models import OnboardingState
from apps.personal.models import (
    Commitment,
    Debt,
    EssentialEstimate,
    IncomeSource,
    PersonalProfile,
    Preference,
    SavingsGoal,
)
from apps.workspaces.models import Workspace


@dataclass(frozen=True)
class Step:
    key: str
    title: str
    question: str
    weight: int
    required: bool
    impact: str  # qué pasa con el plan si falta


STEPS: tuple[Step, ...] = (
    Step("ingresos", "Ingresos", "¿Cuánto recibes y cuándo?", 30, True,
         "Sin ingresos no podemos calcular cuánto puedes gastar."),
    Step("compromisos", "Compromisos fijos", "¿Qué pagos fijos tienes cada mes?", 15, True,
         "El plan no reservará dinero para alquiler, servicios ni colegio."),
    Step("esenciales", "Gastos del día a día", "¿Cuánto gastas en lo esencial?", 20, True,
         "El plan te mostrará más dinero libre del que realmente tienes."),
    Step("ahorro", "Meta de ahorro", "¿Quieres ahorrar para algo?", 10, False,
         "No apartaremos dinero para tus metas."),
    Step("cuentas", "Tu dinero hoy", "¿Cuánto tienes en cada cuenta?", 10, False,
         "'Disponible para gastar' no reflejará tu dinero real."),
    Step("deudas", "Deudas", "¿Pagas cuotas de algún préstamo o tarjeta?", 5, False,
         "Las cuotas no se reservarán en sus fechas."),
    Step("preferencias", "Tus prioridades", "¿Qué es prioritario y qué podrías reducir?", 10, False,
         "Las sugerencias no seguirán lo que más te importa."),
)  # fmt: skip
STEP_KEYS = tuple(s.key for s in STEPS)
STEPS_BY_KEY = {s.key: s for s in STEPS}

BUSINESS_STEPS: tuple[Step, ...] = (
    Step("perfil", "Tu negocio", "¿A qué se dedica tu negocio?", 15, True,
         "No sabremos si cobras ITBIS ni cuántas horas puedes trabajar."),
    Step("productos", "Productos y costos", "¿Qué vendes, a qué precio y cuánto te cuesta?", 35,
         True, "Sin productos no podemos estimar ventas ni ganancia."),
    Step("gastos", "Gastos fijos", "¿Qué gastos fijos tiene el negocio?", 20, False,
         "El resultado y el punto de equilibrio quedarán inflados."),
    Step("efectivo", "Dinero del negocio", "¿Cuánto dinero tiene hoy el negocio?", 10, False,
         "No podremos avisarte de fechas con riesgo de caja."),
    Step("objetivos", "Tus metas", "¿Qué margen y ganancia quieres, y cuánto retirar?", 20, False,
         "No podremos sugerir precios ni decirte cuánto puedes retirar."),
)  # fmt: skip
BUSINESS_STEP_KEYS = tuple(s.key for s in BUSINESS_STEPS)
BUSINESS_STEPS_BY_KEY = {s.key: s for s in BUSINESS_STEPS}


def steps_for(workspace: Workspace) -> tuple[Step, ...]:
    return BUSINESS_STEPS if workspace.is_business else STEPS


def get_state(workspace: Workspace) -> OnboardingState:
    state, _ = OnboardingState.objects.get_or_create(workspace=workspace)
    return state


def _has_data(workspace: Workspace, key: str) -> bool:
    ws = workspace
    checks = {
        "ingresos": lambda: IncomeSource.objects.for_workspace(ws).exists(),
        "compromisos": lambda: Commitment.objects.for_workspace(ws).exists(),
        "esenciales": lambda: EssentialEstimate.objects.for_workspace(ws).exists(),
        "ahorro": lambda: SavingsGoal.objects.for_workspace(ws).exists(),
        "cuentas": lambda: (
            Account.objects.for_workspace(ws).exclude(opening_balance=0).exists()
            or Transaction.objects.for_workspace(ws).exists()
        ),
        "deudas": lambda: Debt.objects.for_workspace(ws).exists(),
        # Negocio
        "perfil": lambda: BusinessProfile.objects.filter(workspace=ws).exists(),
        "productos": lambda: Product.objects.for_workspace(ws).exists(),
        "gastos": lambda: OperatingExpense.objects.for_workspace(ws).exists(),
        "efectivo": lambda: (
            Account.objects.for_workspace(ws).exclude(opening_balance=0).exists()
            or Transaction.objects.for_workspace(ws).exists()
        ),
        "objetivos": lambda: BusinessGoal.objects.filter(workspace=ws).exists(),
        "preferencias": lambda: (
            Preference.objects.for_workspace(ws).exists()
            or PersonalProfile.objects.filter(workspace=ws).exists()
        ),
    }
    return checks[key]()


@dataclass(frozen=True)
class StepProgress:
    step: Step
    done: bool
    skipped: bool


@dataclass(frozen=True)
class Completeness:
    percent: int
    steps: tuple[StepProgress, ...]

    @property
    def missing(self) -> list[StepProgress]:
        return [s for s in self.steps if not s.done]

    @property
    def minimum_ready(self) -> bool:
        return all(s.done for s in self.steps if s.step.required)


def completeness(workspace: Workspace) -> Completeness:
    """Un paso cuenta como hecho si tiene datos o si la persona lo respondió (aunque sea con
    "no tengo"). Omitirlo no lo completa."""
    state = get_state(workspace)
    steps = steps_for(workspace)
    progress = tuple(
        StepProgress(
            step=s,
            done=s.key in state.answered_steps or _has_data(workspace, s.key),
            skipped=s.key in state.skipped_steps,
        )
        for s in steps
    )
    total = sum(s.weight for s in steps)
    done = sum(p.step.weight for p in progress if p.done)
    return Completeness(percent=round(done * 100 / total), steps=progress)


def next_step(current: str, keys: tuple[str, ...] = STEP_KEYS) -> str | None:
    index = keys.index(current)
    return keys[index + 1] if index + 1 < len(keys) else None


def previous_step(current: str, keys: tuple[str, ...] = STEP_KEYS) -> str | None:
    index = keys.index(current)
    return keys[index - 1] if index > 0 else None
