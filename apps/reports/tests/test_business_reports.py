import datetime
import uuid
from decimal import Decimal

import pytest

from apps.business.models import BusinessProfile, Product
from apps.business.services.purchases import PurchaseData, PurchaseLineData, register_purchase
from apps.business.services.sales import SaleData, SaleLineData, register_sale
from apps.ledger.models import Account, Category
from apps.ledger.services.sync import parse_item, upsert_from_client
from apps.reports.services.business_reports import (
    TaxSummary,
    last_months,
    month_label,
    monthly_statements,
    statements_csv,
    tax_summary,
)

pytestmark = pytest.mark.django_db
D = Decimal
HOY = datetime.date(2026, 10, 13)


def test_ultimos_meses():
    months = last_months(datetime.date(2026, 3, 13), 4)
    assert months[0] == (datetime.date(2025, 12, 1), datetime.date(2025, 12, 31))
    assert months[1] == (datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))
    assert months[2][1] == datetime.date(2026, 2, 28)
    assert months[-1] == (datetime.date(2026, 3, 1), datetime.date(2026, 3, 13))
    assert month_label(datetime.date(2026, 3, 1)) == "mar 2026"


def test_resumen_itbis():
    s = TaxSummary(collected=D("1800"), paid_purchases=D("900"), paid_expenses=D("180"))
    assert s.paid == D("1080") and s.balance == D("720") and "DGII" in s.note
    assert TaxSummary(D("0"), D("100"), D("0")).balance == D("-100")


@pytest.fixture
def negocio(business_ws, user):
    BusinessProfile.objects.create(workspace=business_ws, activity="Colmado")
    caja = Account.objects.get(workspace=business_ws)
    refresco = Product.objects.create(
        workspace=business_ws, name="Refresco", price=D("100"), unit_cost=D("0"),
        tracks_inventory=True,
    )  # fmt: skip
    register_purchase(business_ws, user, PurchaseData(
        date=datetime.date(2026, 9, 5), lines=[PurchaseLineData(refresco, D("20"), D("50"))],
        account=caja, tax=D("180")))  # fmt: skip
    sept = datetime.date(2026, 9, 10)
    register_sale(business_ws, user, SaleData(
        date=sept, lines=[SaleLineData(refresco, D("5"))], account=caja))  # fmt: skip
    register_sale(business_ws, user, SaleData(
        date=HOY, lines=[SaleLineData(refresco, D("10"))], account=caja))  # fmt: skip
    luz = Category.objects.get(workspace=business_ws, name="Servicios (luz, agua, internet)")
    item = parse_item(business_ws, {
        "client_uuid": str(uuid.uuid4()), "account_id": str(caja.pk), "date": HOY.isoformat(),
        "amount": "1180", "kind": "gasto", "category_id": str(luz.pk), "tax_amount": "180",
    })  # fmt: skip
    upsert_from_client(business_ws, user, item)
    return business_ws


def test_estados_por_mes_y_csv(negocio):
    months = monthly_statements(negocio, HOY, months=3)
    assert [month_label(m.start) for m in months] == ["ago 2026", "sep 2026", "oct 2026"]
    agosto, septiembre, octubre = months
    assert agosto.sales == 0
    assert septiembre.sales == D("500.00") and septiembre.cogs == D("250.00")
    assert septiembre.tax_collected == D("90.00")  # 18 % sobre 500
    assert octubre.sales == D("1000.00") and octubre.operating_expenses == D("1180")
    text = statements_csv(months)
    lines = text.strip().splitlines()
    assert lines[0].startswith("Mes,Ventas sin ITBIS,Costo de lo vendido")
    assert lines[2].startswith("sep 2026,500.00,250.00,250.00,50.00")


def test_itbis_del_mes(negocio):
    sep = tax_summary(negocio, datetime.date(2026, 9, 1), datetime.date(2026, 9, 30))
    assert (sep.collected, sep.paid_purchases, sep.paid_expenses) == (D("90.00"), D("180.00"), 0)
    assert sep.balance == D("-90.00")
    octubre = tax_summary(negocio, datetime.date(2026, 10, 1), HOY)
    assert octubre.collected == D("180.00") and octubre.paid_expenses == D("180.00")
    assert octubre.balance == 0


def test_itbis_invalido_en_sincronizacion(business_ws):
    caja = Account.objects.get(workspace=business_ws)
    base = {"client_uuid": str(uuid.uuid4()), "account_id": str(caja.pk), "date": "2026-10-13",
            "amount": "100", "kind": "gasto"}  # fmt: skip
    from django.core.exceptions import ValidationError

    for bad in ("abc", "-1", "150"):
        with pytest.raises(ValidationError) as exc:
            parse_item(business_ws, {**base, "tax_amount": bad})
        assert "tax_amount" in exc.value.message_dict
