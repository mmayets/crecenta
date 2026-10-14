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
from apps.business.models import (
    BusinessGoal,
    BusinessProfile,
    CostComponent,
    Customer,
    InventoryMovement,
    OperatingExpense,
    Payable,
    Product,
    Purchase,
    PurchaseLine,
    Receivable,
    RecipeItem,
    Sale,
    SaleLine,
    Supplier,
)
from apps.ledger.models import Account, Category, Transaction
from apps.onboarding.models import AssistantSession
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
from apps.workspaces.models import Invitation, Membership, Workspace, WorkspaceTransfer

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
    # Negocio (Fase 2)
    "productos": Product,
    "gastos_operativos": OperatingExpense,
    "clientes": Customer,
    "proveedores": Supplier,
    "ventas": Sale,
    "por_cobrar": Receivable,
    "por_pagar": Payable,
    # Fase 3
    "compras": Purchase,
    "movimientos_de_inventario": InventoryMovement,
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
            "conversacion_con_el_asistente": _rows(AssistantSession.objects.filter(user=user)),
            "transferencias_entre_espacios": _rows(
                WorkspaceTransfer.objects.filter(from_workspace__owner=user)
            ),
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
            if workspace.is_business:
                entry["perfil_negocio"] = _rows(BusinessProfile.objects.filter(workspace=workspace))
                entry["objetivos"] = _rows(BusinessGoal.objects.filter(workspace=workspace))
                entry["componentes_de_costo"] = _rows(
                    CostComponent.objects.filter(product__workspace=workspace)
                )
                entry["lineas_de_venta"] = _rows(SaleLine.objects.filter(sale__workspace=workspace))
                entry["lineas_de_compra"] = _rows(
                    PurchaseLine.objects.filter(purchase__workspace=workspace)
                )
                entry["recetas"] = _rows(RecipeItem.objects.filter(product__workspace=workspace))
                entry["equipo"] = list(
                    Membership.objects.filter(workspace=workspace).values("user__email", "role")
                )
                # Sin el hash del código: el archivo no debe servir para aceptar invitaciones.
                entry["invitaciones"] = list(
                    Invitation.objects.filter(workspace=workspace).values(
                        "email", "role", "created_at", "expires_at", "accepted_at", "revoked_at"
                    )
                )
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
