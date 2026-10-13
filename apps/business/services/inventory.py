"""Inventario con costo promedio ponderado (docs/fase3.md §2).

Parte pura: `weighted_average`, `apply_movement` y `replay` (existencia, promedio y valor a partir
del historial). Parte con ORM: `refresh_stock`, salidas por venta, inventario inicial, mermas,
ajustes por conteo y el resumen de existencias.

- Entradas con costo propio (inventario inicial, compra): recalculan el promedio. Si la existencia
  era cero o negativa, el promedio pasa a ser el costo de la entrada.
- Salidas (venta, merma, ajuste −) y ajustes +: al promedio del momento; no lo cambian.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.core.money import ZERO, q

if TYPE_CHECKING:
    from apps.accounts.models import User
    from apps.business.models import InventoryMovement, Product, SaleLine
    from apps.workspaces.models import Workspace

COST_PLACES = Decimal("0.0001")
QTY_PLACES = Decimal("0.001")
WITH_OWN_COST = frozenset({"inicial", "compra"})


def q4(value: Decimal | int) -> Decimal:
    return Decimal(value).quantize(COST_PLACES, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class MovementInput:
    kind: str  # inicial | compra | venta | merma | ajuste
    qty: Decimal  # con signo
    unit_cost: Decimal = ZERO  # solo cuenta en inicial/compra


@dataclass(frozen=True)
class StockState:
    stock: Decimal = ZERO
    average_cost: Decimal = ZERO

    @property
    def value(self) -> Decimal:
        """Valor del inventario al costo promedio (una existencia negativa no vale nada)."""
        return q(max(self.stock, ZERO) * self.average_cost)


def weighted_average(
    stock: Decimal, average: Decimal, qty_in: Decimal, unit_cost: Decimal
) -> Decimal:
    if qty_in <= 0:
        raise ValueError("La entrada debe ser positiva")
    if stock <= 0:
        return q4(unit_cost)
    return q4((stock * average + qty_in * unit_cost) / (stock + qty_in))


def apply_movement(state: StockState, movement: MovementInput) -> tuple[StockState, Decimal]:
    """Nuevo estado y costo unitario con que se valora el movimiento."""
    if movement.qty == 0:
        raise ValueError("La cantidad no puede ser cero")
    if movement.kind in WITH_OWN_COST:
        if movement.qty < 0 or movement.unit_cost < 0:
            raise ValueError("Una entrada con costo debe tener cantidad y costo positivos")
        average = weighted_average(
            state.stock, state.average_cost, movement.qty, movement.unit_cost
        )
        return StockState(state.stock + movement.qty, average), q4(movement.unit_cost)
    return StockState(state.stock + movement.qty, state.average_cost), state.average_cost


def replay(movements: Iterable[MovementInput]) -> StockState:
    state = StockState()
    for movement in movements:
        state, _ = apply_movement(state, movement)
    return state


# ---------------------------------------------------------------------------- ORM


def _inputs(product: Product) -> list[MovementInput]:
    return [
        MovementInput(m.kind, m.qty, m.unit_cost)
        for m in product.movements.order_by("date", "created_at")
    ]


def refresh_stock(product: Product) -> StockState:
    """Recalcula existencia y promedio desde el historial y los guarda en el producto."""
    state = replay(_inputs(product))
    product.stock = state.stock
    product.average_cost = state.average_cost
    product.save(update_fields=["stock", "average_cost", "updated_at"])
    return state


def _require_tracked(product: Product, workspace: Workspace) -> None:
    if product.workspace_id != workspace.pk:
        raise ValidationError({"product": "El producto no pertenece a este espacio."})
    if not product.tracks_inventory:
        raise ValidationError({"product": "Este producto no tiene control de inventario."})


def _create(
    workspace: Workspace,
    user: User | None,
    product: Product,
    kind: str,
    qty: Decimal,
    on: datetime.date,
    unit_cost: Decimal,
    **links: object,
) -> InventoryMovement:
    from apps.business.models import InventoryMovement

    movement = InventoryMovement(
        workspace=workspace,
        product=product,
        kind=kind,
        date=on,
        qty=qty.quantize(QTY_PLACES),
        unit_cost=q4(unit_cost),
        value=q(qty * unit_cost),
        created_by=user,
        **links,
    )
    movement.save()
    return movement


def record_sale_outflow(workspace: Workspace, line: SaleLine, on: datetime.date) -> Decimal:
    """Salida por una línea de venta al costo promedio del momento; devuelve ese costo."""
    product = line.product
    assert product is not None and product.tracks_inventory
    cost = q4(product.average_cost)  # puede venir como 0 entero si el producto es nuevo
    _create(workspace, None, product, "venta", -line.qty, on, cost, sale_line=line)
    refresh_stock(product)
    return cost


def register_adjustment(
    workspace: Workspace,
    user: User | None,
    product: Product,
    kind: str,
    qty: Decimal,
    on: datetime.date,
    *,
    unit_cost: Decimal | None = None,
    note: str = "",
    client_uuid: uuid.UUID | None = None,
) -> InventoryMovement:
    """Inventario inicial (qty > 0 con costo), merma (qty > 0, sale) o ajuste (qty con signo)."""
    from apps.business.models import InventoryMovement

    _require_tracked(product, workspace)
    if kind == "inicial":
        if qty <= 0 or unit_cost is None or unit_cost < 0:
            raise ValidationError({"qty": "Indica cuántas unidades tienes y a qué costo."})
        signed, cost = qty, unit_cost
    elif kind == "merma":
        if qty <= 0:
            raise ValidationError({"qty": "Indica cuántas unidades se perdieron."})
        signed, cost = -qty, product.average_cost
    elif kind == "ajuste":
        if qty == 0:
            raise ValidationError({"qty": "El conteo coincide: no hay nada que ajustar."})
        signed, cost = qty, product.average_cost
    else:
        raise ValidationError({"kind": "Tipo de movimiento no válido."})

    def existing() -> InventoryMovement | None:
        if client_uuid is None:
            return None
        found: InventoryMovement | None = InventoryMovement.objects.filter(
            workspace=workspace, client_uuid=client_uuid
        ).first()
        return found

    found = existing()
    if found is not None:
        return found
    try:
        with transaction.atomic():
            movement = _create(
                workspace, user, product, kind, signed, on, cost,
                note=note.strip()[:140], client_uuid=client_uuid,
            )  # fmt: skip
            refresh_stock(product)
    except IntegrityError:
        found = existing()
        if found is None:
            raise
        return found
    return movement


def count_stock(
    workspace: Workspace,
    user: User | None,
    product: Product,
    counted: Decimal,
    on: datetime.date,
    client_uuid: uuid.UUID | None = None,
) -> InventoryMovement:
    """Conteo físico: registra un ajuste por la diferencia con la existencia registrada."""
    if counted < 0:
        raise ValidationError({"qty": "El conteo no puede ser negativo."})
    refresh_stock(product)
    return register_adjustment(
        workspace, user, product, "ajuste", counted - product.stock, on,
        note=f"Conteo: {counted.normalize():f}", client_uuid=client_uuid,
    )  # fmt: skip


def delete_movement(workspace: Workspace, movement: InventoryMovement) -> None:
    """Borra un movimiento manual (inicial, merma o ajuste). Compras y ventas se anulan desde su
    pantalla para no descuadrar el efectivo."""
    if movement.workspace_id != workspace.pk:
        raise ValidationError("No pertenece a este espacio.")
    if movement.purchase_line_id or movement.sale_line_id:
        raise ValidationError("Este movimiento es de una compra o venta: anúlala desde allí.")
    product = movement.product
    movement.delete()
    refresh_stock(product)
