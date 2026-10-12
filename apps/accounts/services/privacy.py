"""Exportar todos los datos de la persona y eliminar su cuenta."""

from __future__ import annotations

import csv
import io
import json
import tempfile
import zipfile
from typing import IO, Any

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.accounts.models import User
from apps.alerts.models import Alert, AlertRule
from apps.ledger.models import Account, Category, Transaction
from apps.personal.models import (
    Commitment,
    Debt,
    EssentialEstimate,
    IncomeSource,
    PersonalProfile,
    Preference,
    SavingsGoal,
)
from apps.planning.models import PlanVersion
from apps.receipts.models import Receipt
from apps.workspaces.models import Workspace

SECTIONS: dict[str, Any] = {
    "cuentas": Account,
    "categorias": Category,
    "movimientos": Transaction,
    "ingresos": IncomeSource,
    "compromisos": Commitment,
    "deudas": Debt,
    "esenciales": EssentialEstimate,
    "metas_ahorro": SavingsGoal,
    "preferencias": Preference,
    "planes": PlanVersion,
    "alertas": Alert,
    "reglas_de_alertas": AlertRule,
    "comprobantes": Receipt,
}
CSV_COLUMNS = [
    "date",
    "kind",
    "direction",
    "amount",
    "category__name",
    "account__name",
    "description",
    "status",
    "source",
]


def _rows(qs: QuerySet) -> list[dict[str, Any]]:
    return list(qs.values())


def owned_workspaces(user: User) -> QuerySet[Workspace]:
    return Workspace.objects.filter(owner=user)


def build_export(user: User) -> IO[bytes]:
    """ZIP con datos.json (todo), un CSV de movimientos por espacio y los comprobantes."""
    buffer: IO[bytes] = tempfile.SpooledTemporaryFile(max_size=20 * 1024 * 1024)  # noqa: SIM115
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        data: dict[str, Any] = {
            "exportado": timezone.now(),
            "usuario": {
                "correo": user.email,
                "nombre": user.first_name,
                "registro": user.date_joined,
                "acepta_ia": user.ai_consent,
            },
            "espacios": [],
        }
        for workspace in owned_workspaces(user):
            entry: dict[str, Any] = {
                "id": workspace.pk,
                "nombre": workspace.name,
                "tipo": workspace.kind,
                "moneda": workspace.currency,
                "perfil": _rows(PersonalProfile.objects.filter(workspace=workspace)),
            }
            for name, model in SECTIONS.items():
                entry[name] = _rows(model.objects.for_workspace(workspace))
            data["espacios"].append(entry)

            text = io.StringIO()
            writer = csv.writer(text)
            writer.writerow(
                [
                    "fecha",
                    "tipo",
                    "sentido",
                    "monto",
                    "categoria",
                    "cuenta",
                    "descripcion",
                    "estado",
                    "origen",
                ]
            )
            for row in (
                Transaction.objects.for_workspace(workspace)
                .order_by("date")
                .values_list(*CSV_COLUMNS)
            ):
                writer.writerow(row)
            archive.writestr(f"movimientos-{workspace.pk}.csv", text.getvalue().encode("utf-8-sig"))

            for receipt in Receipt.objects.for_workspace(workspace):
                if receipt.file and receipt.file.storage.exists(receipt.file.name):
                    with receipt.file.open("rb") as handle:
                        archive.writestr(
                            f"comprobantes/{receipt.file.name.split('/')[-1]}", handle.read()
                        )
        archive.writestr(
            "datos.json",
            json.dumps(data, cls=DjangoJSONEncoder, ensure_ascii=False, indent=1).encode(),
        )
    buffer.seek(0)
    return buffer


@transaction.atomic
def delete_account(user: User) -> int:
    """Elimina la cuenta, todos los espacios que le pertenecen y sus archivos. Devuelve cuántos
    archivos se borraron."""
    files = [
        (r.file.storage, r.file.name)
        for r in Receipt.objects.filter(workspace__owner=user)
        if r.file and r.file.name
    ]
    owned_workspaces(user).delete()
    user.delete()

    def remove_files() -> None:
        for storage, name in files:
            storage.delete(name)

    transaction.on_commit(remove_files)
    return len(files)
