"""Carga el caso RD$50,000 del encargo en un espacio (para tests con base de datos)."""

from decimal import Decimal

from apps.personal.services.demo import category as cat
from apps.personal.services.demo import load_personal_case

D = Decimal

__all__ = ["D", "cat", "load_caso_50000"]


def load_caso_50000(ws, salary="50000"):
    return load_personal_case(ws, salary=salary)
