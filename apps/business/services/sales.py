"""Ventas, cuentas por cobrar y por pagar (docs/fase2.md §1).

- Venta de contado: crea la venta y un movimiento `venta` por el total cobrado.
- Venta a crédito: crea la venta y una CxC; el efectivo entra al cobrar (`cobro_cxc`).
- Cobros y pagos parciales actualizan lo abonado; nunca se cobra o paga más que el saldo.
- Todo es idempotente con `client_uuid`: reenviar el mismo registro devuelve el existente.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction

from apps.accounts.models import User
from apps.business.models import (
    BusinessProfile,
    Customer,
    InventoryMovement,
    Payable,
    Product,
    Receivable,
    Sale,
    SaleLine,
    Supplier,
)
from apps.core.money import ZERO, fmt, q, to_money
from apps.ledger.choices import CategoryGroup, Direction, TxKind, TxSource
from apps.ledger.models import Account, Category, Transaction
from apps.workspaces.models import Workspace

from .inventory import record_recipe_outflows, record_sale_outflow, refresh_stock
from .product_cost import current_unit_cost
from .sale_math import LineInput, sale_totals

SALES_CATEGORY = "Ventas"
# Espacio de nombres para derivar el id del movimiento de una venta de contado.
_SALE_TX_NS = uuid.UUID("0b8e7c6a-52f1-4d3e-9a10-7c2b4e8f6d31")


@dataclass(frozen=True)
class SaleLineData:
    product: Product | None
    qty: Decimal
    unit_price: Decimal | None = None  # None → precio del producto
    discount_pct: Decimal = ZERO
    description: str = ""


@dataclass(frozen=True)
class SaleData:
    date: datetime.date
    lines: list[SaleLineData]
    payment: str = Sale.Payment.CONTADO
    account: Account | None = None
    customer: Customer | None = None
    customer_name: str = ""  # crea o reutiliza el cliente por nombre
    due_date: datetime.date | None = None  # vencimiento de la CxC (crédito)
    apply_tax: bool = True
    note: str = ""
    client_uuid: uuid.UUID | None = None
    source: str = TxSource.MANUAL
    ncf: str = ""  # comprobante fiscal emitido (opcional)
    customer_tax_id: str = ""  # RNC o cédula del cliente (se guarda en el cliente)


@dataclass(frozen=True)
class DebtData:
    concept: str
    amount: Decimal
    due_date: datetime.date | None = None
    counterpart_name: str = ""  # cliente (CxC) o proveedor (CxP), por nombre
    category: Category | None = None  # solo CxP
    client_uuid: uuid.UUID | None = None


def _require_business(workspace: Workspace) -> None:
    if not workspace.is_business:
        raise ValidationError("Esta operación es solo para espacios de negocio.")


def _check_owned(workspace: Workspace, obj: models.Model | None, field_name: str) -> None:
    if obj is not None and getattr(obj, "workspace_id", None) != workspace.pk:
        raise ValidationError({field_name: "No pertenece a este espacio."})


def _idempotent[T: models.Model](
    model: type[T], workspace: Workspace, client_uuid: uuid.UUID | None, create: Callable[[], T]
) -> tuple[T, bool]:
    """Crea con `create()` salvo que ya exista un registro con ese `client_uuid` en el espacio."""

    def existing() -> T | None:
        if client_uuid is None:
            return None
        found: T | None = model._default_manager.filter(
            workspace=workspace, client_uuid=client_uuid
        ).first()
        return found

    found = existing()
    if found is not None:
        return found, False
    try:
        with transaction.atomic():
            return create(), True
    except IntegrityError:
        found = existing()
        if found is None:
            raise
        return found, False


def clean_code(value: str) -> str:
    """NCF, RNC o cédula: sin espacios ni guiones y en mayúsculas."""
    return "".join(ch for ch in value if ch not in " -").upper()


def set_tax_id(counterpart: Customer | Supplier | None, tax_id: str) -> None:
    """Guarda el RNC o cédula de la contraparte (si se escribió) y lo valida."""
    tax_id = clean_code(tax_id)
    if tax_id and counterpart is None:
        raise ValidationError({"tax_id": "Escribe también el nombre del cliente o proveedor."})
    if counterpart is None or not tax_id or counterpart.tax_id == tax_id:
        return
    counterpart.tax_id = tax_id
    try:
        counterpart.full_clean(validate_constraints=False)
    except ValidationError as exc:
        raise ValidationError({"tax_id": exc.message_dict.get("tax_id", exc.messages)}) from exc
    counterpart.save(update_fields=["tax_id", "updated_at"])


def get_or_create_named[T: models.Model](
    model: type[T], workspace: Workspace, name: str
) -> T | None:
    """Cliente o proveedor por nombre (sin distinguir mayúsculas). Vacío → None."""
    name = " ".join(name.split())[:120]
    if not name:
        return None
    found: T | None = model._default_manager.filter(workspace=workspace, name__iexact=name).first()
    if found is not None:
        return found
    created: T = model._default_manager.create(workspace=workspace, name=name)
    return created


def _sales_category(workspace: Workspace) -> Category | None:
    return (
        Category.objects.for_workspace(workspace)
        .filter(group=CategoryGroup.INGRESO, name=SALES_CATEGORY)
        .first()
    )


def _profile(workspace: Workspace) -> BusinessProfile | None:
    return BusinessProfile.objects.filter(workspace=workspace).first()


# ---------------------------------------------------------------------------- ventas


def register_sale(workspace: Workspace, user: User | None, data: SaleData) -> tuple[Sale, bool]:
    """Registra una venta. Devuelve (venta, creada)."""
    _require_business(workspace)
    return _idempotent(
        Sale, workspace, data.client_uuid, lambda: _create_sale(workspace, user, data)
    )


def _create_sale(
    workspace: Workspace, user: User | None, data: SaleData, existing: Sale | None = None
) -> Sale:
    """Valida y escribe la venta con sus líneas, salidas de inventario y su movimiento o CxC.
    Con `existing` reescribe una venta ya guardada (edición) conservando su id."""
    errors: dict[str, str] = {}
    if not data.lines:
        errors["lines"] = "Agrega al menos un producto."
    for line in data.lines:
        if line.product is not None and (
            line.product.workspace_id != workspace.pk or not line.product.is_active
        ):
            errors["lines"] = "Hay un producto que no está disponible en este negocio."
        if line.product is not None and line.product.is_supply:
            errors["lines"] = "Un insumo no se vende: véndelo como parte de un producto."
        if line.product is None and (line.unit_price is None or not line.description.strip()):
            errors["lines"] = "Sin producto, indica descripción y precio."
    _check_owned(workspace, data.account, "account")
    _check_owned(workspace, data.customer, "customer")
    if errors:
        raise ValidationError(errors)

    profile = _profile(workspace)
    tax_rate = profile.tax_rate_itbis if profile and data.apply_tax else ZERO
    include_tax = bool(profile and profile.prices_include_tax and data.apply_tax)
    prices = [
        q(to_money(line.unit_price)) if line.unit_price is not None else line.product.price  # type: ignore[union-attr]
        for line in data.lines
    ]
    try:
        totals = sale_totals(
            [
                LineInput(qty=to_money(line.qty), unit_price=price, discount_pct=line.discount_pct)
                for line, price in zip(data.lines, prices, strict=True)
            ],
            tax_rate,
            prices_include_tax=include_tax,
        )
    except ValueError as exc:
        raise ValidationError({"lines": str(exc)}) from exc
    if totals.total <= 0:
        raise ValidationError({"lines": "La venta debe tener un total mayor que cero."})

    customer = data.customer or get_or_create_named(Customer, workspace, data.customer_name)
    sale = existing or Sale(workspace=workspace, client_uuid=data.client_uuid, created_by=user)
    sale.date = data.date
    sale.customer = customer
    sale.payment = data.payment
    sale.account = data.account if data.payment == Sale.Payment.CONTADO else None
    sale.subtotal = totals.subtotal
    sale.tax = totals.tax
    sale.total = totals.total
    sale.note = data.note.strip()[:140]
    sale.ncf = clean_code(data.ncf)
    set_tax_id(customer, data.customer_tax_id)
    if sale.ncf and (
        Sale.objects.for_workspace(workspace).filter(ncf=sale.ncf).exclude(pk=sale.pk).exists()
    ):
        raise ValidationError({"ncf": "Ese NCF ya está en otra venta."})
    if data.payment == Sale.Payment.CREDITO and data.account is not None:
        raise ValidationError({"account": "Una venta a crédito no mueve dinero hasta cobrarse."})
    sale.full_clean(validate_constraints=False)
    sale.save()
    for line, price, net in zip(data.lines, prices, totals.line_nets, strict=True):
        product = line.product
        tracked = product is not None and product.tracks_inventory
        has_recipe = product is not None and not tracked and product.recipe.exists()
        sale_line = SaleLine.objects.create(
            sale=sale,
            product=product,
            description=(line.description or (product.name if product else ""))[:120],
            qty=to_money(line.qty),
            unit_price=price,
            discount_pct=line.discount_pct,
            net_amount=net,
            # Con inventario, el costo es el promedio del momento; si no, el costo del producto.
            unit_cost_snapshot=current_unit_cost(product) if product else ZERO,
        )
        if tracked:
            record_sale_outflow(workspace, sale_line, data.date)
        elif has_recipe:
            record_recipe_outflows(workspace, sale_line, data.date)
    concept = _sale_concept(sale)
    if data.payment == Sale.Payment.CONTADO:
        assert data.account is not None
        tx = Transaction(
            workspace=workspace,
            account=data.account,
            date=data.date,
            amount=totals.total,
            direction=Direction.IN,
            kind=TxKind.VENTA,
            category=_sales_category(workspace),
            description=concept,
            source=data.source,
            client_uuid=uuid.uuid5(_SALE_TX_NS, str(data.client_uuid))
            if data.client_uuid
            else None,
            sale=sale,
            created_by=user,
        )
        tx.full_clean(validate_constraints=False)
        tx.save()
    else:
        Receivable.objects.create(
            workspace=workspace,
            customer=customer,
            sale=sale,
            concept=concept,
            amount=totals.total,
            due_date=data.due_date,
            created_by=user,
        )
    return sale


def _sale_concept(sale: Sale) -> str:
    lines = list(sale.lines.all()[:3])
    text = ", ".join(f"{line.qty.normalize():f} {line.description}" for line in lines)
    who = f" a {sale.customer.name}" if sale.customer else ""
    return f"Venta{who}: {text}"[:140]


def _tracked_products(sale: Sale) -> list[Product]:
    """Productos e insumos cuyo inventario movió la venta."""
    ids = (
        InventoryMovement.objects.filter(sale_line__sale=sale)
        .values_list("product_id", flat=True)
        .distinct()
    )
    return list(Product.objects.filter(pk__in=list(ids)))


def _check_no_collections(sale: Sale, action: str) -> None:
    receivable = Receivable.objects.filter(sale=sale).first()
    if receivable is not None and receivable.paid > 0:
        raise ValidationError(
            f"Esta venta ya tiene cobros registrados. Elimina primero los cobros para {action}."
        )


def delete_sale(workspace: Workspace, sale: Sale) -> None:
    """Anula una venta: borra sus líneas, sus salidas de inventario, su movimiento de contado y su
    CxC sin cobros, y recalcula las existencias."""
    _check_owned(workspace, sale, "sale")
    _check_no_collections(sale, "anularla")
    products = _tracked_products(sale)
    with transaction.atomic():
        sale.delete()
        for product in set(products):
            refresh_stock(product)


def edit_sale(workspace: Workspace, user: User | None, sale: Sale, data: SaleData) -> Sale:
    """Reescribe una venta sin cobros con los datos nuevos (mismo id). Revierte y vuelve a
    registrar sus salidas de inventario, su movimiento de contado o su CxC."""
    _require_business(workspace)
    _check_owned(workspace, sale, "sale")
    with transaction.atomic():
        locked = Sale.objects.select_for_update().get(pk=sale.pk)
        _check_no_collections(locked, "editarla")
        products = _tracked_products(locked)
        locked.lines.all().delete()
        Transaction.objects.filter(sale=locked).delete()
        Receivable.objects.filter(sale=locked).delete()
        for product in set(products):
            refresh_stock(product)
            product.refresh_from_db()
        lines = [
            replace(line, product=Product.objects.get(pk=line.product.pk))
            if line.product is not None
            else line
            for line in data.lines
        ]
        return _create_sale(
            workspace, user, replace(data, lines=lines, client_uuid=locked.client_uuid), locked
        )


def stock_warnings(sale: Sale) -> list[str]:
    """Avisos tras vender: productos con inventario que quedaron sin existencias registradas."""
    return [
        f"Vendiste más {product.name} de lo que tenías registrado (existencia "
        f"{product.stock.normalize():f}). Registra la compra o haz un conteo."
        for product in {p.pk: p for p in _tracked_products(sale)}.values()
        if Product.objects.get(pk=product.pk).stock < 0
    ]


# ---------------------------------------------------------------------------- CxC y CxP


def register_receivable(workspace: Workspace, user: User | None, data: DebtData) -> Receivable:
    """CxC sin venta en la app (p. ej. lo que ya te debían al empezar)."""
    _require_business(workspace)

    def create() -> Receivable:
        debt = Receivable(
            workspace=workspace,
            customer=get_or_create_named(Customer, workspace, data.counterpart_name),
            concept=data.concept.strip()[:140],
            amount=q(to_money(data.amount)),
            due_date=data.due_date,
            client_uuid=data.client_uuid,
            created_by=user,
        )
        _validate_debt(debt)
        debt.save()
        return debt

    return _idempotent(Receivable, workspace, data.client_uuid, create)[0]


def register_payable(workspace: Workspace, user: User | None, data: DebtData) -> Payable:
    """Compra a crédito o cualquier pago pendiente a un proveedor."""
    _require_business(workspace)
    _check_owned(workspace, data.category, "category")
    if data.category is not None and data.category.group == CategoryGroup.INGRESO:
        raise ValidationError({"category": "Elige una categoría de costo o gasto."})

    def create() -> Payable:
        debt = Payable(
            workspace=workspace,
            supplier=get_or_create_named(Supplier, workspace, data.counterpart_name),
            concept=data.concept.strip()[:140],
            amount=q(to_money(data.amount)),
            due_date=data.due_date,
            category=data.category,
            client_uuid=data.client_uuid,
            created_by=user,
        )
        _validate_debt(debt)
        debt.save()
        return debt

    return _idempotent(Payable, workspace, data.client_uuid, create)[0]


def _validate_debt(debt: Receivable | Payable) -> None:
    errors: dict[str, str] = {}
    if not debt.concept:
        errors["concept"] = "Escribe el concepto."
    if debt.amount <= 0:
        errors["amount"] = "El monto debe ser mayor que cero."
    if errors:
        raise ValidationError(errors)


def collect_receivable(
    workspace: Workspace,
    user: User | None,
    receivable: Receivable,
    amount: Decimal | str,
    account: Account,
    on: datetime.date,
    client_uuid: uuid.UUID | None = None,
) -> tuple[Transaction, bool]:
    """Cobro total o parcial de una CxC. Devuelve (movimiento `cobro_cxc`, creado)."""
    return _settle(
        workspace, user, receivable, amount, account, on, client_uuid,
        kind=TxKind.COBRO_CXC, direction=Direction.IN,
    )  # fmt: skip


def pay_payable(
    workspace: Workspace,
    user: User | None,
    payable: Payable,
    amount: Decimal | str,
    account: Account,
    on: datetime.date,
    client_uuid: uuid.UUID | None = None,
) -> tuple[Transaction, bool]:
    """Pago total o parcial a un proveedor. Devuelve (movimiento `pago_cxp`, creado)."""
    return _settle(
        workspace, user, payable, amount, account, on, client_uuid,
        kind=TxKind.PAGO_CXP, direction=Direction.OUT,
    )  # fmt: skip


def _settle(
    workspace: Workspace,
    user: User | None,
    debt: Receivable | Payable,
    amount: Decimal | str,
    account: Account,
    on: datetime.date,
    client_uuid: uuid.UUID | None,
    *,
    kind: str,
    direction: str,
) -> tuple[Transaction, bool]:
    _require_business(workspace)
    _check_owned(workspace, debt, "debt")
    _check_owned(workspace, account, "account")
    value = q(to_money(amount))
    is_receivable = isinstance(debt, Receivable)

    def create() -> Transaction:
        locked = type(debt).objects.select_for_update().get(pk=debt.pk)
        if value <= 0:
            raise ValidationError({"amount": "El monto debe ser mayor que cero."})
        if value > locked.balance:
            raise ValidationError(
                {"amount": f"El saldo pendiente es {fmt(locked.balance, workspace.currency)}."}
            )
        tx = Transaction(
            workspace=workspace,
            account=account,
            date=on,
            amount=value,
            direction=direction,
            kind=kind,
            category=None if is_receivable else locked.category,  # type: ignore[union-attr]
            description=("Cobro: " if is_receivable else "Pago: ") + locked.concept[:130],
            client_uuid=client_uuid,
            created_by=user,
            **({"receivable": locked} if is_receivable else {"payable": locked}),
        )
        tx.full_clean(validate_constraints=False)
        tx.save()
        locked.paid = locked.paid + value
        locked.save(update_fields=["paid", "updated_at"])
        debt.refresh_from_db()
        return tx

    return _idempotent(Transaction, workspace, client_uuid, create)


def undo_settlement(workspace: Workspace, tx: Transaction) -> None:
    """Elimina un cobro o pago y devuelve su monto al saldo de la deuda."""
    _check_owned(workspace, tx, "transaction")
    with transaction.atomic():
        debt: Receivable | Payable | None = None
        if tx.receivable_id:
            debt = Receivable.objects.select_for_update().get(pk=tx.receivable_id)
        elif tx.payable_id:
            debt = Payable.objects.select_for_update().get(pk=tx.payable_id)
        if debt is not None:
            debt.paid = max(ZERO, debt.paid - tx.amount)
            debt.save(update_fields=["paid", "updated_at"])
        tx.delete()
