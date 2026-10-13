import datetime
import uuid
from decimal import Decimal
from unittest import mock

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.business.models import (
    BusinessProfile,
    Customer,
    DebtStatus,
    Payable,
    Product,
    Receivable,
    Sale,
    Supplier,
)
from apps.business.services import sales as svc
from apps.business.services.sales import (
    DebtData,
    SaleData,
    SaleLineData,
    collect_receivable,
    delete_sale,
    get_or_create_named,
    pay_payable,
    register_payable,
    register_receivable,
    register_sale,
    undo_settlement,
)
from apps.ledger.choices import TxKind
from apps.ledger.models import Account, Category, Transaction
from apps.ledger.services.balances import account_balance
from apps.workspaces.services.workspaces import create_workspace

D = Decimal
HOY = datetime.date(2026, 10, 13)


@pytest.fixture
def caja(business_ws):
    return Account.objects.get(workspace=business_ws)


@pytest.fixture
def bizcocho(business_ws):
    return Product.objects.create(
        workspace=business_ws, name="Bizcocho", price=D("857.14"), unit_cost=D("600")
    )


def contado(bizcocho, caja, qty="2", **kw):
    return SaleData(
        date=HOY, lines=[SaleLineData(bizcocho, D(qty))], payment="contado", account=caja, **kw
    )


def credito(bizcocho, qty="1", **kw):
    return SaleData(date=HOY, lines=[SaleLineData(bizcocho, D(qty))], payment="credito", **kw)


def test_venta_de_contado_crea_movimiento_de_venta(business_ws, user, bizcocho, caja):
    sale, created = register_sale(business_ws, user, contado(bizcocho, caja, customer_name="Luisa"))
    assert (
        created and sale.subtotal == D("1714.28") and sale.tax == 0 and sale.total == D("1714.28")
    )
    line = sale.lines.get()
    assert line.unit_cost_snapshot == D("600") and line.net_amount == D("1714.28")
    tx = Transaction.objects.get(sale=sale)
    assert tx.kind == TxKind.VENTA and tx.amount == D("1714.28") and tx.category.name == "Ventas"
    assert tx.description == "Venta a Luisa: 2 Bizcocho"
    assert not Receivable.objects.exists()
    assert account_balance(caja) == D("1714.28")
    # El costo guardado no cambia si después cambia el del producto.
    bizcocho.unit_cost = D("700")
    bizcocho.save()
    line.refresh_from_db()
    assert line.unit_cost_snapshot == D("600")


def test_venta_a_credito_no_mueve_efectivo_hasta_cobrarse(business_ws, user, bizcocho, caja):
    due = HOY + datetime.timedelta(days=15)
    sale, _ = register_sale(
        business_ws, user, credito(bizcocho, customer_name="Pedro", due_date=due)
    )
    cxc = sale.receivable
    assert cxc.amount == D("857.14") and cxc.due_date == due and cxc.customer.name == "Pedro"
    assert not Transaction.objects.filter(workspace=business_ws).exists()
    assert account_balance(caja) == 0

    tx, created = collect_receivable(business_ws, user, cxc, "300", caja, HOY)
    assert created and tx.kind == TxKind.COBRO_CXC and tx.receivable == cxc
    assert tx.description.startswith("Cobro: Venta a Pedro")
    cxc.refresh_from_db()
    assert cxc.status == DebtStatus.PARCIAL and cxc.balance == D("557.14")
    assert account_balance(caja) == D("300")

    with pytest.raises(ValidationError) as exc:
        collect_receivable(business_ws, user, cxc, "600", caja, HOY)
    assert "RD$557.14" in exc.value.message_dict["amount"][0]
    collect_receivable(business_ws, user, cxc, "557.14", caja, HOY)
    cxc.refresh_from_db()
    assert cxc.status == DebtStatus.PAGADA


def test_itbis_sumado_y_excluido_de_ventas(business_ws, user, bizcocho, caja):
    BusinessProfile.objects.create(workspace=business_ws, activity="Repostería")
    sale, _ = register_sale(business_ws, user, contado(bizcocho, caja, qty="1"))
    assert sale.subtotal == D("857.14") and sale.tax == D("154.29") and sale.total == D("1011.43")
    sin, _ = register_sale(business_ws, user, contado(bizcocho, caja, qty="1", apply_tax=False))
    assert sin.tax == 0


def test_itbis_incluido_en_el_precio(business_ws, user, caja):
    BusinessProfile.objects.create(
        workspace=business_ws, activity="Repostería", prices_include_tax=True
    )
    data = SaleData(
        date=HOY,
        lines=[SaleLineData(None, D("1"), unit_price=D("1180"), description="Torta especial")],
        account=caja,
    )
    sale, _ = register_sale(business_ws, user, data)
    assert sale.total == D("1180.00") and sale.subtotal == D("1000.00") and sale.tax == D("180.00")
    assert sale.lines.get().unit_cost_snapshot == 0


def test_doble_envio_no_duplica(business_ws, user, bizcocho, caja):
    uid = uuid.uuid4()
    first, c1 = register_sale(business_ws, user, contado(bizcocho, caja, client_uuid=uid))
    second, c2 = register_sale(business_ws, user, contado(bizcocho, caja, client_uuid=uid))
    assert c1 and not c2 and first.pk == second.pk
    assert Sale.objects.count() == 1 and Transaction.objects.count() == 1

    cobro_uid = uuid.uuid4()
    sale, _ = register_sale(business_ws, user, credito(bizcocho))
    t1, n1 = collect_receivable(business_ws, user, sale.receivable, "100", caja, HOY, cobro_uid)
    t2, n2 = collect_receivable(business_ws, user, sale.receivable, "100", caja, HOY, cobro_uid)
    assert n1 and not n2 and t1.pk == t2.pk
    sale.receivable.refresh_from_db()
    assert sale.receivable.paid == D("100")

    deuda = DebtData(concept="Harina", amount=D("5000"), client_uuid=uuid.uuid4())
    assert (
        register_payable(business_ws, user, deuda).pk
        == register_payable(business_ws, user, deuda).pk
    )


def test_carrera_de_venta_devuelve_la_existente(business_ws, user, bizcocho, caja):
    uid = uuid.uuid4()
    existing, _ = register_sale(business_ws, user, contado(bizcocho, caja, client_uuid=uid))
    calls = {"n": 0}
    real_filter = Sale._default_manager.filter

    def fake_filter(*args, **kwargs):
        calls["n"] += 1
        qs = real_filter(*args, **kwargs)
        return qs.none() if calls["n"] == 1 else qs

    with mock.patch.object(Sale._default_manager, "filter", side_effect=fake_filter):
        sale, created = register_sale(business_ws, user, contado(bizcocho, caja, client_uuid=uid))
    assert not created and sale.pk == existing.pk


def test_integrity_error_sin_existente_se_propaga(business_ws, user, bizcocho, caja):
    with (
        mock.patch.object(svc, "_create_sale", side_effect=IntegrityError("x")),
        pytest.raises(IntegrityError),
    ):
        register_sale(business_ws, user, contado(bizcocho, caja, client_uuid=uuid.uuid4()))


def test_validaciones_de_venta(business_ws, personal_ws, user, bizcocho, caja):
    with pytest.raises(ValidationError):
        register_sale(personal_ws, user, contado(bizcocho, caja))
    with pytest.raises(ValidationError) as exc:
        register_sale(business_ws, user, SaleData(date=HOY, lines=[], account=caja))
    assert "lines" in exc.value.message_dict
    with pytest.raises(ValidationError):  # contado sin cuenta
        register_sale(business_ws, user, SaleData(date=HOY, lines=[SaleLineData(bizcocho, D("1"))]))
    with pytest.raises(ValidationError) as exc:  # crédito con cuenta
        register_sale(business_ws, user, credito(bizcocho, account=caja))
    assert "account" in exc.value.message_dict
    with pytest.raises(ValidationError):  # sin producto ni descripción
        register_sale(
            business_ws, user,
            SaleData(date=HOY, lines=[SaleLineData(None, D("1"), unit_price=D("5"))], account=caja),
        )  # fmt: skip
    with pytest.raises(ValidationError):  # cantidad cero
        register_sale(business_ws, user, contado(bizcocho, caja, qty="0"))
    gratis = SaleLineData(bizcocho, D("1"), discount_pct=D("1"))
    with pytest.raises(ValidationError) as exc:
        register_sale(business_ws, user, SaleData(date=HOY, lines=[gratis], account=caja))
    assert "mayor que cero" in exc.value.message_dict["lines"][0]
    bizcocho.is_active = False
    bizcocho.save()
    with pytest.raises(ValidationError):
        register_sale(business_ws, user, contado(bizcocho, caja))


def test_no_acepta_objetos_de_otro_espacio(business_ws, user, bizcocho, caja):
    otro = create_workspace(user, "business", name="Otro")
    ajena = Account.objects.get(workspace=otro)
    ajeno = Product.objects.create(workspace=otro, name="X", price=D("1"), unit_cost=D("0"))
    with pytest.raises(ValidationError):
        register_sale(business_ws, user, contado(bizcocho, ajena))
    with pytest.raises(ValidationError):
        register_sale(business_ws, user, contado(ajeno, caja))
    cliente = Customer.objects.create(workspace=otro, name="Z")
    with pytest.raises(ValidationError):
        register_sale(business_ws, user, credito(bizcocho, customer=cliente))
    sale, _ = register_sale(business_ws, user, credito(bizcocho))
    with pytest.raises(ValidationError):
        collect_receivable(otro, user, sale.receivable, "1", ajena, HOY)
    with pytest.raises(ValidationError):
        collect_receivable(business_ws, user, sale.receivable, "1", ajena, HOY)


def test_cliente_por_nombre_se_reutiliza(business_ws):
    a = get_or_create_named(Customer, business_ws, "  maría   pérez ")
    b = get_or_create_named(Customer, business_ws, "María Pérez")
    assert a.pk == b.pk and a.name == "maría pérez"
    assert get_or_create_named(Supplier, business_ws, "   ") is None


def test_cxp_pago_parcial_y_categoria(business_ws, user, caja):
    materia = Category.objects.get(workspace=business_ws, name="Materia prima")
    data = DebtData(
        concept="Harina a crédito", amount=D("5000"), counterpart_name="Molino", category=materia
    )
    cxp = register_payable(business_ws, user, data)
    assert cxp.supplier.name == "Molino" and cxp.status == DebtStatus.PENDIENTE
    tx, _ = pay_payable(business_ws, user, cxp, "2000", caja, HOY)
    assert tx.kind == TxKind.PAGO_CXP and tx.category == materia and tx.payable == cxp
    cxp.refresh_from_db()
    assert cxp.status == DebtStatus.PARCIAL and account_balance(caja) == D("-2000")
    with pytest.raises(ValidationError):
        pay_payable(business_ws, user, cxp, "0", caja, HOY)

    undo_settlement(business_ws, tx)
    cxp.refresh_from_db()
    assert cxp.paid == 0 and cxp.status == DebtStatus.PENDIENTE
    assert not Transaction.objects.exists()


def test_validaciones_de_deudas(business_ws, user):
    ventas = Category.objects.get(workspace=business_ws, name="Ventas")
    with pytest.raises(ValidationError):
        register_payable(business_ws, user, DebtData(concept="x", amount=D("1"), category=ventas))
    with pytest.raises(ValidationError) as exc:
        register_receivable(business_ws, user, DebtData(concept=" ", amount=D("0")))
    assert {"concept", "amount"} <= set(exc.value.message_dict)
    cxc = register_receivable(
        business_ws,
        user,
        DebtData(concept="Saldo anterior", amount=D("2500"), counterpart_name="Ana"),
    )
    assert cxc.sale is None and cxc.customer.name == "Ana" and Payable.objects.count() == 0


def test_anular_venta(business_ws, user, bizcocho, caja):
    sale, _ = register_sale(business_ws, user, contado(bizcocho, caja))
    delete_sale(business_ws, sale)
    assert not Sale.objects.exists() and not Transaction.objects.exists()

    sale, _ = register_sale(business_ws, user, credito(bizcocho))
    tx, _ = collect_receivable(business_ws, user, sale.receivable, "100", caja, HOY)
    with pytest.raises(ValidationError):
        delete_sale(business_ws, sale)
    undo_settlement(business_ws, tx)
    delete_sale(business_ws, sale)
    assert not Receivable.objects.exists()


def test_deshacer_movimiento_sin_deuda(business_ws, user, caja):
    tx = Transaction.objects.create(
        workspace=business_ws, account=caja, date=HOY, amount=D("5"), direction="out", kind="gasto"
    )
    undo_settlement(business_ws, tx)
    assert not Transaction.objects.exists()


def test_borrar_desde_movimientos_respeta_ventas_y_cobros(
    client, business_ws, user, bizcocho, caja
):
    from django.urls import reverse

    client.force_login(user)

    def borrar(tx):
        return client.post(reverse("ledger:delete", kwargs={"ws": business_ws.pk, "tx_id": tx.pk}))

    sale, _ = register_sale(business_ws, user, contado(bizcocho, caja))
    borrar(Transaction.objects.get(sale=sale))
    assert Transaction.objects.filter(sale=sale).exists()  # se anula desde Ventas

    venta, _ = register_sale(business_ws, user, credito(bizcocho))
    cobro, _ = collect_receivable(business_ws, user, venta.receivable, "200", caja, HOY)
    borrar(cobro)
    venta.receivable.refresh_from_db()
    assert venta.receivable.paid == 0 and not Transaction.objects.filter(pk=cobro.pk).exists()
