import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.business.models import (
    CostComponent,
    Customer,
    DebtStatus,
    OperatingExpense,
    Payable,
    Product,
    Receivable,
    Sale,
    SaleLine,
    status_for,
)
from apps.business.services.costs import refresh_unit_cost
from apps.ledger.models import Account, Category
from apps.workspaces.services.workspaces import create_workspace

D = Decimal
HOY = datetime.date(2026, 10, 13)


@pytest.fixture
def product(business_ws):
    return Product.objects.create(
        workspace=business_ws, name="Bizcocho", price=D("857.14"), unit_cost=D("0")
    )


def test_refrescar_costo_unitario_desde_componentes(product):
    assert refresh_unit_cost(product) == D("0")  # sin componentes, se respeta el manual
    CostComponent.objects.create(
        product=product, name="Harina y más", type="materia", amount=D("500")
    )
    CostComponent.objects.create(
        product=product, name="Comisión", type="comision_pct", amount=D("0.10")
    )
    assert refresh_unit_cost(product) == D("585.71")
    product.refresh_from_db()
    assert product.unit_cost == D("585.71")


def test_comision_debe_ser_fraccion(product):
    comp = CostComponent(product=product, name="Comisión", type="comision_pct", amount=D("10"))
    with pytest.raises(ValidationError):
        comp.full_clean()
    assert not CostComponent(
        product=product, name="x", type="materia", amount=D("10")
    ).is_percentage


@pytest.mark.parametrize(
    ("amount", "paid", "status"),
    [
        (D("100"), D("0"), DebtStatus.PENDIENTE),
        (D("100"), D("40"), DebtStatus.PARCIAL),
        (D("100"), D("100"), DebtStatus.PAGADA),
    ],
)
def test_estado_por_abono(amount, paid, status):
    assert status_for(amount, paid) == status


def test_cxc_estado_y_vencimiento(business_ws):
    cxc = Receivable.objects.create(
        workspace=business_ws, concept="Bizcocho", amount=D("1000"), due_date=HOY
    )
    assert cxc.status == DebtStatus.PENDIENTE and cxc.balance == D("1000")
    assert not cxc.is_overdue(HOY) and cxc.is_overdue(HOY + datetime.timedelta(days=1))
    cxc.paid = D("400")
    cxc.save(update_fields=["paid"])
    cxc.refresh_from_db()
    assert cxc.status == DebtStatus.PARCIAL and cxc.balance == D("600")
    cxc.paid = D("1000")
    cxc.save()
    assert cxc.status == DebtStatus.PAGADA and not cxc.is_overdue(HOY + datetime.timedelta(days=9))


def test_abono_no_supera_monto(business_ws):
    cxp = Payable(workspace=business_ws, concept="Harina", amount=D("100"), paid=D("150"))
    with pytest.raises(ValidationError):
        cxp.full_clean()
    with pytest.raises(IntegrityError):
        cxp.save()


def test_venta_contado_requiere_cuenta_y_credito_no(business_ws):
    account = Account.objects.get(workspace=business_ws)
    contado = Sale(workspace=business_ws, date=HOY, payment=Sale.Payment.CONTADO)
    with pytest.raises(ValidationError) as exc:
        contado.full_clean()
    assert "account" in exc.value.message_dict
    credito = Sale(workspace=business_ws, date=HOY, payment=Sale.Payment.CREDITO, account=account)
    with pytest.raises(ValidationError):
        credito.full_clean()
    contado.account = account
    contado.full_clean()


def test_venta_rechaza_cliente_o_cuenta_de_otro_espacio(business_ws, user):
    otro = create_workspace(user, "business", name="Otro negocio")
    ajeno = Customer.objects.create(workspace=otro, name="María")
    cuenta_ajena = Account.objects.get(workspace=otro)
    sale = Sale(
        workspace=business_ws, date=HOY, payment="contado", account=cuenta_ajena, customer=ajeno
    )
    with pytest.raises(ValidationError) as exc:
        sale.full_clean()
    assert {"customer", "account"} <= set(exc.value.message_dict)


def test_linea_de_venta_valida_producto(business_ws, product, user):
    sale = Sale.objects.create(workspace=business_ws, date=HOY, payment="credito")
    with pytest.raises(ValidationError):
        SaleLine(sale=sale, qty=D("1"), unit_price=D("10")).full_clean()
    otro = create_workspace(user, "business", name="Otro negocio")
    ajeno = Product.objects.create(workspace=otro, name="X", price=D("1"), unit_cost=D("0"))
    with pytest.raises(ValidationError):
        SaleLine(sale=sale, product=ajeno, qty=D("1"), unit_price=D("10")).full_clean()
    line = SaleLine(sale=sale, product=product, qty=D("2"), unit_price=D("857.14"))
    line.full_clean()
    line.save()
    assert str(line).startswith("2")


def test_gasto_operativo_categoria_del_mismo_espacio(business_ws, user):
    otro = create_workspace(user, "business", name="Otro negocio")
    ajena = Category.objects.filter(workspace=otro).first()
    gasto = OperatingExpense(
        workspace=business_ws, name="Alquiler", amount=D("15000"), category=ajena
    )
    with pytest.raises(ValidationError):
        gasto.full_clean()
    gasto.category = Category.objects.get(workspace=business_ws, name="Alquiler del local")
    gasto.full_clean()


def test_client_uuid_de_venta_unico_por_espacio(business_ws):
    import uuid

    uid = uuid.uuid4()
    Sale.objects.create(workspace=business_ws, date=HOY, payment="credito", client_uuid=uid)
    with pytest.raises(IntegrityError):
        Sale.objects.create(workspace=business_ws, date=HOY, payment="credito", client_uuid=uid)
