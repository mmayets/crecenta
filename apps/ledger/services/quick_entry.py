"""Registro rápido por texto libre o voz: la IA interpreta la frase y devuelve un **borrador** que
la persona revisa en el formulario rápido. Nunca se guarda sin confirmación."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from apps.accounts.models import User
from apps.ai.schemas import QuickEntry
from apps.ai.services.client import run_structured
from apps.ledger.choices import CategoryGroup, TxKind
from apps.ledger.models import Account, Category
from apps.ledger.services.categories import match_account, match_category
from apps.workspaces.models import Workspace

LOW_CONFIDENCE = 0.6
_EXPENSE_GROUPS = [g for g in CategoryGroup.values if g not in (CategoryGroup.INGRESO,)]


@dataclass(frozen=True)
class QuickDraft:
    kind: str  # gasto | ingreso | transferencia_interna | retiro_efectivo | pago_deuda
    amount: Decimal
    date: date
    description: str
    category: Category | None
    account: Account | None
    doubtful: frozenset[str] = field(default_factory=frozenset)

    def initial(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "amount": self.amount,
            "date": self.date,
            "description": self.description,
            "category": self.category.pk if self.category else None,
            "account": self.account.pk if self.account else None,
        }


def parse_free_text(workspace: Workspace, user: User | None, text: str, today: date) -> QuickDraft:
    """Interpreta "gasté 350 en el colmado ayer" (lanza AIUnavailable si no hay IA)."""
    categories = list(
        Category.objects.for_workspace(workspace)
        .filter(is_archived=False)
        .values_list("name", flat=True)
    )
    accounts = list(
        Account.objects.for_workspace(workspace)
        .filter(is_archived=False)
        .values_list("name", flat=True)
    )
    result = run_structured(
        workspace=workspace,
        user=user,
        purpose="registro_rapido",
        prompt_name="registro_rapido",
        context={
            "hoy": today.isoformat(),
            "texto": text[:500],
            "categorias": categories,
            "cuentas": accounts,
        },
        schema=QuickEntry,
    )
    return draft_from_entry(workspace, result.data, today)


def draft_from_entry(workspace: Workspace, entry: QuickEntry, today: date) -> QuickDraft:
    groups = [CategoryGroup.INGRESO] if entry.tipo == TxKind.INGRESO else _EXPENSE_GROUPS
    category = match_category(workspace, entry.categoria, *groups)
    account = match_account(workspace, entry.cuenta)
    confidence = entry.confianza
    doubtful = {
        name
        for name, source in (
            ("amount", "monto"),
            ("date", "fecha"),
            ("category", "categoria"),
            ("account", "cuenta"),
        )
        if float(confidence.get(source, 1 if source == "monto" else 0)) < LOW_CONFIDENCE
    }
    if category is None:
        doubtful.add("category")
    if account is None:
        doubtful.add("account")
        account = Account.objects.for_workspace(workspace).filter(is_archived=False).first()
    if entry.fecha is None:
        doubtful.add("date")
    return QuickDraft(
        kind=entry.tipo,
        amount=entry.monto,
        date=entry.fecha or today,
        description=entry.descripcion,
        category=category,
        account=account,
        doubtful=frozenset(doubtful),
    )
