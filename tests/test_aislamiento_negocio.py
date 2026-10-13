"""Aislamiento del negocio (Fase 2).

El test general recorre las rutas contra un espacio *personal* ajeno, y las rutas de negocio
responden 404 ahí por ser de otro tipo. Aquí se prueba lo que importa en el negocio:
1. todas las rutas contra el *negocio* de otra persona responden 404;
2. objetos de otro espacio referidos por id en la URL de mi propio negocio responden 404;
3. ids ajenos en los formularios (producto, cuenta, categoría, cuenta personal) se rechazan.
"""

import uuid
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.business.models import Payable, Product, Receivable, Sale
from apps.business.services.sales import (
    DebtData,
    SaleData,
    SaleLineData,
    register_payable,
    register_sale,
)
from apps.ledger.models import Account, Category
from apps.workspaces.models import WorkspaceTransfer
from apps.workspaces.services.workspaces import create_workspace
from tests.test_aislamiento import ROUTES, build_url

pytestmark = pytest.mark.django_db
D = Decimal
BUSINESS_ROUTES = [(ns, p) for ns, p in ROUTES if ns == "business"]


@pytest.fixture
def ajeno(other_user):
    """Negocio de otra persona con venta a crédito, producto y deuda."""
    ws = create_workspace(other_user, "business", name="Colmado Beto")
    product = Product.objects.create(workspace=ws, name="Pan", price=D("10"), unit_cost=D("5"))
    sale, _ = register_sale(
        ws, other_user, SaleData(date="2026-10-10", lines=[SaleLineData(product, D("1"))],
                                 payment="credito")
    )  # fmt: skip
    register_payable(ws, other_user, DebtData(concept="Harina", amount=D("100")))
    return ws


@pytest.fixture
def logged(client, user):
    client.force_login(user)
    return client


def test_hay_rutas_de_negocio():
    assert len(BUSINESS_ROUTES) >= 14


@pytest.mark.parametrize(
    ("namespace", "pattern"), BUSINESS_ROUTES, ids=lambda v: getattr(v, "name", v)
)
@pytest.mark.parametrize("method", ["get", "post"])
def test_negocio_ajeno_responde_404(logged, ajeno, namespace, pattern, method):
    response = getattr(logged, method)(build_url(namespace, pattern, ajeno.pk))
    assert response.status_code == 404


def test_objetos_ajenos_en_mi_negocio_responden_404(logged, business_ws, ajeno):
    sale = Sale.objects.get(workspace=ajeno)
    product = Product.objects.get(workspace=ajeno)
    cxc = Receivable.objects.get(workspace=ajeno)
    cxp = Payable.objects.get(workspace=ajeno)
    mine = {"ws": business_ws.pk}
    for name, kwargs in (
        ("sale_detail", {"sale_id": sale.pk}),
        ("sale_delete", {"sale_id": sale.pk}),
        ("product_edit", {"product_id": product.pk}),
        ("collect", {"debt_id": cxc.pk}),
        ("pay", {"debt_id": cxp.pk}),
    ):
        url = reverse(f"business:{name}", kwargs={**mine, **kwargs})
        codes = {logged.get(url).status_code, logged.post(url).status_code}
        assert codes <= {404, 405} and 404 in codes  # 405: método no permitido, sin tocar datos
    pricing = reverse("business:pricing", kwargs=mine) + f"?producto={product.pk}"
    assert logged.get(pricing).status_code == 404
    assert Sale.objects.filter(pk=sale.pk).exists()


def test_ids_ajenos_en_formularios_se_rechazan(logged, user, business_ws, personal_ws, ajeno):
    mine = {"ws": business_ws.pk}
    my_product = Product.objects.create(
        workspace=business_ws, name="Bizcocho", price=D("857.14"), unit_cost=D("600")
    )
    foreign_account = Account.objects.get(workspace=ajeno)
    foreign_product = Product.objects.get(workspace=ajeno)
    venta = {
        "client_uuid": str(uuid.uuid4()), "date": "2026-10-13", "payment": "contado",
        "account": str(foreign_account.pk), "producto_1": str(my_product.pk), "cantidad_1": "1",
    }  # fmt: skip
    assert logged.post(reverse("business:sale_new", kwargs=mine), venta).status_code == 400
    venta.update(account=str(Account.objects.get(workspace=business_ws).pk),
                 producto_1=str(foreign_product.pk))  # fmt: skip
    assert logged.post(reverse("business:sale_new", kwargs=mine), venta).status_code == 400
    assert not Sale.objects.filter(workspace=business_ws).exists()

    foreign_category = Category.objects.filter(workspace=ajeno, group="costo_variable").first()
    deuda = {"client_uuid": str(uuid.uuid4()), "concept": "x", "amount": "10",
             "category": str(foreign_category.pk)}  # fmt: skip
    assert logged.post(reverse("business:payables", kwargs=mine), deuda).status_code == 400

    cxc = Receivable.objects.create(workspace=business_ws, concept="Mío", amount=D("50"))
    cobro = {"client_uuid": str(uuid.uuid4()), "amount": "10", "account": str(foreign_account.pk),
             "date": "2026-10-13"}  # fmt: skip
    url = reverse("business:collect", kwargs={**mine, "debt_id": cxc.pk})
    assert logged.post(url, cobro).status_code == 400

    # La cuenta personal debe ser de MI espacio personal, no la de otra persona.
    other_personal = create_workspace(ajeno.owner, "personal")
    retiro = {
        "client_uuid": str(uuid.uuid4()), "kind": "retiro_propietario", "amount": "10",
        "account": str(Account.objects.get(workspace=business_ws).pk),
        "personal_account": str(Account.objects.get(workspace=other_personal).pk),
        "date": "2026-10-13",
    }  # fmt: skip
    assert logged.post(reverse("business:owner", kwargs=mine), retiro).status_code == 400
    assert not WorkspaceTransfer.objects.exists()
