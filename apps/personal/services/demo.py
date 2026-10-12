"""Datos del caso del encargo (§7): salario neto RD$50,000 → compromisos 20,000; esenciales
15,000; ahorro 7,000; ocio 5,000; reserva 3,000. Lo usan `seed_demo` y los tests."""

from __future__ import annotations

from decimal import Decimal

from apps.ledger.models import Category
from apps.personal.models import (
    Commitment,
    EssentialEstimate,
    IncomeSource,
    PersonalProfile,
    Preference,
    SavingsGoal,
)
from apps.workspaces.models import Workspace

COMMITMENTS = [
    ("Alquiler", "15000", 5, "Alquiler o hipoteca"),
    ("Electricidad", "2500", 15, "Electricidad"),
    ("Internet", "2500", 20, "Internet y teléfono"),
]
ESSENTIALS = [("Alimentación", "10000"), ("Transporte y combustible", "5000")]


def category(workspace: Workspace, name: str) -> Category:
    found: Category = Category.objects.for_workspace(workspace).get(name=name)
    return found


def load_personal_case(workspace: Workspace, salary: str = "50000") -> Workspace:
    IncomeSource.objects.create(
        workspace=workspace, name="Salario", net_amount=Decimal(salary), pay_days=[1]
    )
    for name, amount, day, category_name in COMMITMENTS:
        Commitment.objects.create(
            workspace=workspace,
            name=name,
            amount=Decimal(amount),
            due_day=day,
            category=category(workspace, category_name),
        )
    for category_name, amount in ESSENTIALS:
        EssentialEstimate.objects.create(
            workspace=workspace, category=category(workspace, category_name), amount=Decimal(amount)
        )
    SavingsGoal.objects.create(
        workspace=workspace,
        purpose="Fondo de emergencia",
        target_amount=Decimal("60000"),
        contribution_amount=Decimal("7000"),
    )
    PersonalProfile.objects.create(workspace=workspace, discretionary_wish=Decimal("5000"))
    Preference.objects.create(
        workspace=workspace, category=category(workspace, "Alimentación"), priority="reducible"
    )
    return workspace
