from decimal import Decimal

from apps.business.models import BusinessProfile, CostComponent, Product
from apps.pricing.services.engine import compute_price
from apps.pricing.services.loaders import inputs_for_product

D = Decimal


def test_entradas_desde_producto_con_componentes(business_ws):
    profile = BusinessProfile.objects.create(workspace=business_ws, activity="Repostería")
    product = Product.objects.create(
        workspace=business_ws, name="Bizcocho", price=D("1000"), unit_cost=D("0")
    )
    CostComponent.objects.create(product=product, name="Materia", type="materia", amount=D("500"))
    CostComponent.objects.create(product=product, name="Entrega", type="entrega", amount=D("100"))
    CostComponent.objects.create(product=product, name="App", type="comision_pct", amount=D("0.10"))
    inputs = inputs_for_product(product, profile, D("0.30"))
    assert inputs.unit_cost == D("600") and inputs.commission_pct == D("0.10")
    assert inputs.tax_rate == D("0.180") and inputs.currency == "DOP"
    assert compute_price(inputs).net_price == D("1000.00")


def test_entradas_desde_producto_sin_componentes(business_ws):
    product = Product.objects.create(
        workspace=business_ws, name="Bizcocho", price=D("857.14"), unit_cost=D("600")
    )
    inputs = inputs_for_product(product, None, D("0.30"), discount_pct=D("0.05"))
    assert inputs.unit_cost == D("600") and inputs.commission_pct == 0 and inputs.tax_rate == 0
    assert inputs.discount_pct == D("0.05")
