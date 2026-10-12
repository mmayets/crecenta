"""Carga el caso RD$50,000 del encargo en un espacio (para tests con base de datos)."""

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

D = Decimal


def cat(ws, name):
    return Category.objects.for_workspace(ws).get(name=name)


def load_caso_50000(ws, salary="50000"):
    IncomeSource.objects.create(workspace=ws, name="Salario", net_amount=D(salary), pay_days=[1])
    for name, amount, day, category in [
        ("Alquiler", "15000", 5, "Alquiler o hipoteca"),
        ("Electricidad", "2500", 15, "Electricidad"),
        ("Internet", "2500", 20, "Internet y teléfono"),
    ]:
        Commitment.objects.create(
            workspace=ws, name=name, amount=D(amount), due_day=day, category=cat(ws, category)
        )
    EssentialEstimate.objects.create(workspace=ws, category=cat(ws, "Alimentación"), amount=10000)
    EssentialEstimate.objects.create(
        workspace=ws, category=cat(ws, "Transporte y combustible"), amount=5000
    )
    SavingsGoal.objects.create(
        workspace=ws, purpose="Fondo de emergencia", contribution_amount=D("7000")
    )
    PersonalProfile.objects.create(workspace=ws, discretionary_wish=D("5000"))
    Preference.objects.create(workspace=ws, category=cat(ws, "Alimentación"), priority="reducible")
    return ws
