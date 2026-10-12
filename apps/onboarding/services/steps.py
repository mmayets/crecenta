"""Pasos del onboarding personal y completitud del perfil.

Los pasos mínimos (ingresos, compromisos, esenciales) bastan para un primer plan; el resto se puede
omitir y completar después. La completitud indica qué falta y cómo afecta la calidad del plan.
"""

from __future__ import annotations

from dataclasses import dataclass

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
    progress = tuple(
        StepProgress(
            step=s,
            done=s.key in state.answered_steps or _has_data(workspace, s.key),
            skipped=s.key in state.skipped_steps,
        )
        for s in STEPS
    )
    total = sum(s.weight for s in STEPS)
    done = sum(p.step.weight for p in progress if p.done)
    return Completeness(percent=round(done * 100 / total), steps=progress)


def next_step(current: str) -> str | None:
    index = STEP_KEYS.index(current)
    return STEP_KEYS[index + 1] if index + 1 < len(STEP_KEYS) else None


def previous_step(current: str) -> str | None:
    index = STEP_KEYS.index(current)
    return STEP_KEYS[index - 1] if index > 0 else None
