"""Negocio de demostración "Dulces Ana" (repostería), cargado con los servicios reales.

- Perfil sin ITBIS (vende sin comprobante fiscal), metas: margen 30 %, ganancia RD$15,000,
  reserva RD$5,000 y retiro mensual de RD$10,000.
- Productos: bizcocho (costo RD$600 por componentes → RD$857.14 al 30 %), cupcake (margen bajo)
  y torta de boda (margen alto, se vende poco).
- Gastos fijos, ventas del mes anterior y del mes en curso (contado y crédito), un cobro parcial,
  una compra a crédito y un retiro del propietario hacia la persona.
- Fase 3: refrescos de reventa con inventario (inventario inicial, compras de contado con ITBIS y
  a crédito, ventas al costo promedio y una merma) y un gasto con ITBIS.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from apps.accounts.models import User
from apps.business.models import (
    BusinessGoal,
    BusinessProfile,
    CostComponent,
    OperatingExpense,
    Product,
    Sale,
)
from apps.business.services.costs import refresh_unit_cost
from apps.business.services.inventory import register_adjustment
from apps.business.services.purchases import PurchaseData, PurchaseLineData, register_purchase
from apps.business.services.sales import (
    DebtData,
    SaleData,
    SaleLineData,
    collect_receivable,
    register_payable,
    register_sale,
)
from apps.core.dates import add_months, clamp_day
from apps.ledger.choices import Direction, TxKind
from apps.ledger.models import Account, Category, Transaction
from apps.ledger.services.recording import create_account
from apps.pricing.services.margins import price_from_margin
from apps.workspaces.models import Workspace, WorkspaceTransfer
from apps.workspaces.services.transfers import transfer_between

D = Decimal
BIZCOCHO = "Bizcocho de vainilla (1 lb)"


def _product(
    ws: Workspace, name: str, price: Decimal, units: str, parts: list[tuple[str, str, str]]
) -> Product:
    product = Product.objects.create(
        workspace=ws, name=name, price=price, unit_cost=D("0"), expected_monthly_units=D(units)
    )
    for part_name, kind, amount in parts:
        CostComponent.objects.create(product=product, name=part_name, type=kind, amount=D(amount))
    refresh_unit_cost(product)
    return product


def load_business_case(
    ws: Workspace, user: User, personal: Workspace, today: datetime.date
) -> None:
    BusinessProfile.objects.create(
        workspace=ws, activity="Repostería", tax_rate_itbis=D("0"), hours_available_month=160
    )
    BusinessGoal.objects.create(
        workspace=ws,
        target_margin_pct=D("0.30"),
        target_profit=D("15000"),
        cash_reserve=D("5000"),
        planned_owner_draw=D("10000"),
    )
    biz = _product(
        ws, BIZCOCHO, price_from_margin(D("600"), D("0.30")).price, "60",
        [("Harina, huevos y mantequilla", "materia", "500"), ("Caja y cinta", "empaque", "50"),
         ("Entrega", "entrega", "50")],
    )  # fmt: skip
    cup = _product(
        ws, "Cupcake decorado", D("100"), "150",
        [("Ingredientes", "materia", "65"), ("Cápsula y caja", "empaque", "15")],
    )  # fmt: skip
    boda = _product(
        ws, "Torta de boda", D("6000"), "3",
        [("Ingredientes y decoración", "materia", "2600"), ("Base y caja", "empaque", "400")],
    )  # fmt: skip

    refresco = Product.objects.create(
        workspace=ws, name="Refresco de 2 litros", price=D("120"), unit_cost=D("0"),
        expected_monthly_units=D("80"), tracks_inventory=True, stock_minimum=D("12"),
    )  # fmt: skip

    cats = {c.name: c for c in Category.objects.for_workspace(ws)}
    for name, amount, freq, day, cat, reducible in (
        ("Alquiler del local", "8000", "mensual", 5, "Alquiler del local", False),
        ("Ayudante", "6000", "quincenal", 15, "Nómina", False),
        ("Luz e internet", "2500", "mensual", 20, "Servicios (luz, agua, internet)", False),
        ("Publicidad en redes", "2000", "mensual", 10, "Publicidad", True),
    ):
        OperatingExpense.objects.create(
            workspace=ws, name=name, amount=D(amount), frequency=freq, due_day=day,
            category=cats[cat], is_reducible=reducible,
        )  # fmt: skip

    caja = Account.objects.for_workspace(ws).get(name="Efectivo")
    caja.opening_balance = D("12000")
    caja.save(update_fields=["opening_balance", "updated_at"])
    banco = create_account(ws, "Banco del negocio", "banco", "28000")

    start = today.replace(day=1)
    year, month = add_months(today.year, today.month, -1)
    prev_start = datetime.date(year, month, 1)

    def on(base: datetime.date, day: int) -> datetime.date:
        limit = today if base == start else clamp_day(year, month, 31)
        return min(clamp_day(base.year, base.month, day), limit)

    def sell(when: datetime.date, lines: list, credit: str = "", account: Account = caja) -> Sale:
        data = SaleData(
            date=when,
            lines=[SaleLineData(p, D(q)) for p, q in lines],
            payment="credito" if credit else "contado",
            account=None if credit else account,
            customer_name=credit,
            due_date=when + datetime.timedelta(days=15) if credit else None,
        )
        return register_sale(ws, user, data)[0]

    def buy(
        when: datetime.date, product: Product, qty: str, cost: str, account: Account | None = None,
        tax: str = "0", supplier: str = "", due: datetime.date | None = None,
    ) -> None:  # fmt: skip
        data = PurchaseData(
            date=when, lines=[PurchaseLineData(product, D(qty), D(cost))],
            payment="contado" if account else "credito", account=account,
            supplier_name=supplier, tax=D(tax), due_date=due,
        )  # fmt: skip
        register_purchase(ws, user, data)

    def spend(when: datetime.date, amount: str, category: str, kind: str = TxKind.GASTO) -> None:
        Transaction.objects.create(
            workspace=ws, account=banco, date=when, amount=D(amount), direction=Direction.OUT,
            kind=kind, category=cats[category], description=category, created_by=user,
        )  # fmt: skip

    # Mes anterior: base para comparar costos y estimar unidades.
    register_adjustment(ws, user, refresco, "inicial", D("24"), prev_start, unit_cost=D("70"))
    buy(on(prev_start, 10), refresco, "48", "72", account=banco, tax="622.08")
    for day, lines in (
        (3, [(biz, "8"), (cup, "30"), (refresco, "20")]),
        (12, [(biz, "10"), (cup, "40"), (refresco, "25")]),
        (20, [(biz, "12"), (boda, "1")]),
        (27, [(biz, "6"), (cup, "35"), (refresco, "15")]),
    ):
        sell(on(prev_start, day), lines, account=banco)  # fmt: skip
    spend(on(prev_start, 2), "9000", "Materia prima", TxKind.COMPRA_INVENTARIO)
    spend(on(prev_start, 5), "8000", "Alquiler del local")
    spend(on(prev_start, 15), "6000", "Nómina")

    # Mes en curso (hasta hoy).
    buy(on(start, 1), refresco, "48", "75", supplier="Distribuidora del Este",
        due=today + datetime.timedelta(days=10))  # fmt: skip
    sell(on(start, 2), [(biz, "6"), (cup, "25"), (refresco, "18")])
    register_adjustment(ws, user, refresco, "merma", D("2"), on(start, 5), note="Botellas rotas")
    Transaction.objects.create(
        workspace=ws, account=banco, date=on(start, 4), amount=D("2950"), direction=Direction.OUT,
        kind=TxKind.GASTO, category=cats["Servicios (luz, agua, internet)"],
        description="Luz e internet (con comprobante)", tax_amount=D("450"), created_by=user,
    )  # fmt: skip
    sell(on(start, 4), [(biz, "4")], credit="Luisa Pérez")
    pedido = sell(on(start, 6), [(boda, "1")], credit="Hotel Bella Vista")
    sell(on(start, 8), [(cup, "40")], account=banco)
    collect_receivable(ws, user, pedido.receivable, "3000", banco, on(start, 9))
    spend(on(start, 1), "7500", "Materia prima", TxKind.COMPRA_INVENTARIO)
    spend(on(start, 3), "1200", "Comisiones")
    spend(on(start, 5), "8000", "Alquiler del local")
    register_payable(
        ws, user,
        DebtData(concept="Harina y azúcar (a crédito)", amount=D("5000"),
                 counterpart_name="Molino del Cibao", category=cats["Materia prima"],
                 due_date=today + datetime.timedelta(days=5)),
    )  # fmt: skip
    efectivo_personal = Account.objects.for_workspace(personal).get(name="Efectivo")
    transfer_between(
        user, ws, personal, "5000", on(start, 7), WorkspaceTransfer.Kind.RETIRO_PROPIETARIO,
        caja, efectivo_personal, note="Para la casa",
    )  # fmt: skip
