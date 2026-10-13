"""Compras de mercancía (Fase 3): entran al inventario con su costo y, según la forma de pago,
crean un movimiento de efectivo (`compra_inventario`, no es gasto) o una cuenta por pagar."""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounts.models import User
from apps.business.models import NCF, Payable, Product, Purchase, PurchaseLine, Supplier
from apps.core.money import ZERO, q, to_money
from apps.ledger.choices import CategoryGroup, Direction, TxKind
from apps.ledger.models import Account, Category, Transaction
from apps.workspaces.models import Workspace

from .inventory import _create, refresh_stock
from .sales import (
    _check_owned,
    _idempotent,
    _require_business,
    clean_code,
    get_or_create_named,
    set_tax_id,
)

PURCHASE_CATEGORY = "Compras de mercancía"
_TX_NS = uuid.UUID("3c1f9a7e-8b2d-4e61-a5c0-7d9e2f4b6a18")


@dataclass(frozen=True)
class PurchaseLineData:
    product: Product
    qty: Decimal
    unit_cost: Decimal  # sin ITBIS


@dataclass(frozen=True)
class PurchaseData:
    date: datetime.date
    lines: list[PurchaseLineData]
    payment: str = Purchase.Payment.CONTADO
    account: Account | None = None
    supplier_name: str = ""
    tax: Decimal = ZERO  # ITBIS pagado en la factura
    due_date: datetime.date | None = None
    note: str = ""
    client_uuid: uuid.UUID | None = None
    ncf: str = ""  # NCF de la factura del proveedor (opcional)
    supplier_tax_id: str = ""  # RNC o cédula del proveedor (se guarda en el proveedor)


def purchase_category(workspace: Workspace) -> Category:
    category, _ = Category.objects.get_or_create(
        workspace=workspace,
        name=PURCHASE_CATEGORY,
        defaults={"group": CategoryGroup.COSTO_VARIABLE, "is_system": True},
    )
    return category


def register_purchase(
    workspace: Workspace, user: User | None, data: PurchaseData
) -> tuple[Purchase, bool]:
    _require_business(workspace)
    return _idempotent(
        Purchase, workspace, data.client_uuid, lambda: _create_purchase(workspace, user, data)
    )


def _validate(workspace: Workspace, data: PurchaseData) -> None:
    errors: dict[str, str] = {}
    if not data.lines:
        errors["lines"] = "Agrega al menos un producto."
    for line in data.lines:
        if line.product.workspace_id != workspace.pk or not line.product.tracks_inventory:
            errors["lines"] = "Solo se compran productos con control de inventario de este negocio."
        if line.qty <= 0 or line.unit_cost < 0:
            errors["lines"] = "Cantidad y costo deben ser positivos."
    if data.tax < 0:
        errors["tax"] = "El ITBIS no puede ser negativo."
    if data.ncf:
        try:
            NCF(clean_code(data.ncf))
        except ValidationError as exc:
            errors["ncf"] = exc.messages[0]
    if data.payment == Purchase.Payment.CONTADO and data.account is None:
        errors["account"] = "Indica de qué cuenta salió el dinero."
    _check_owned(workspace, data.account, "account")
    if errors:
        raise ValidationError(errors)


def _create_purchase(workspace: Workspace, user: User | None, data: PurchaseData) -> Purchase:
    _validate(workspace, data)
    subtotal = sum((q(line.qty * line.unit_cost) for line in data.lines), ZERO)
    tax = q(to_money(data.tax))
    total = subtotal + tax
    if total <= 0:
        raise ValidationError({"lines": "La compra debe tener un total mayor que cero."})
    credit = data.payment == Purchase.Payment.CREDITO
    supplier = get_or_create_named(Supplier, workspace, data.supplier_name)
    set_tax_id(supplier, data.supplier_tax_id)
    purchase = Purchase.objects.create(
        workspace=workspace,
        date=data.date,
        supplier=supplier,
        payment=data.payment,
        account=None if credit else data.account,
        client_uuid=data.client_uuid,
        subtotal=subtotal,
        tax=tax,
        total=total,
        note=data.note.strip()[:140],
        ncf=clean_code(data.ncf),
        created_by=user,
    )
    for item in data.lines:
        line = PurchaseLine.objects.create(
            purchase=purchase, product=item.product, qty=item.qty, unit_cost=item.unit_cost
        )
        _create(workspace, user, item.product, "compra", item.qty, data.date, item.unit_cost,
                purchase_line=line)  # fmt: skip
        refresh_stock(item.product)
    names = ", ".join(f"{i.qty.normalize():f} {i.product.name}" for i in data.lines[:3])
    concept = (f"Compra a {supplier.name}: " if supplier else "Compra: ") + names
    category = purchase_category(workspace)
    if credit:
        Payable.objects.create(
            workspace=workspace,
            supplier=supplier,
            concept=concept[:140],
            amount=total,
            due_date=data.due_date,
            category=category,
            purchase=purchase,
            created_by=user,
        )
    else:
        assert data.account is not None
        tx = Transaction(
            workspace=workspace,
            account=data.account,
            date=data.date,
            amount=total,
            direction=Direction.OUT,
            kind=TxKind.COMPRA_INVENTARIO,
            category=category,
            description=concept[:140],
            client_uuid=uuid.uuid5(_TX_NS, str(data.client_uuid)) if data.client_uuid else None,
            purchase=purchase,
            tax_amount=tax,
            created_by=user,
        )
        tx.full_clean(validate_constraints=False)
        tx.save()
    return purchase


def delete_purchase(workspace: Workspace, purchase: Purchase) -> None:
    """Anula una compra (sus entradas, su movimiento o su CxP) si no tiene pagos registrados."""
    _check_owned(workspace, purchase, "purchase")
    payable = Payable.objects.filter(purchase=purchase).first()
    if payable is not None and payable.paid > 0:
        raise ValidationError("Esta compra ya tiene pagos al proveedor. Elimina primero los pagos.")
    products = list({line.product for line in purchase.lines.select_related("product")})
    with transaction.atomic():
        purchase.delete()
        for product in products:
            refresh_stock(product)
