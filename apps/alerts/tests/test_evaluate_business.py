import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.alerts.models import Alert, AlertRule
from apps.alerts.services.evaluate import evaluate_workspace
from apps.business.models import BusinessGoal, OperatingExpense, Product
from apps.business.services.sales import SaleData, SaleLineData, register_sale
from apps.ledger.models import Account, Category, Transaction
from apps.workspaces.models import WorkspaceTransfer
from apps.workspaces.services.transfers import transfer_between

pytestmark = pytest.mark.django_db
D = Decimal
HOY = datetime.date(2026, 10, 13)


@pytest.fixture
def negocio(business_ws, personal_ws, user):
    ws = business_ws
    caja = Account.objects.get(workspace=ws)
    caja.opening_balance = D("12000")
    caja.save()
    cup = Product.objects.create(workspace=ws, name="Cupcake", price=D("100"), unit_cost=D("80"))
    register_sale(ws, user, SaleData(date=HOY, lines=[SaleLineData(cup, D("50"))], account=caja))
    comisiones = Category.objects.get(workspace=ws, name="Comisiones")
    for day, amount in ((datetime.date(2026, 9, 5), "500"), (datetime.date(2026, 10, 5), "1500")):
        Transaction.objects.create(
            workspace=ws, account=caja, date=day, amount=D(amount), direction="out",
            kind="gasto", category=comisiones,
        )  # fmt: skip
    register_sale(
        ws, user,
        SaleData(date=datetime.date(2026, 9, 6), lines=[SaleLineData(cup, D("50"))], account=caja),
    )  # fmt: skip
    OperatingExpense.objects.create(workspace=ws, name="Alquiler", amount=D("20000"), due_day=20)
    BusinessGoal.objects.create(workspace=ws, target_margin_pct=D("0.30"))
    transfer_between(
        user, ws, personal_ws, "4000", datetime.date(2026, 10, 10),
        WorkspaceTransfer.Kind.RETIRO_PROPIETARIO, caja, Account.objects.get(workspace=personal_ws),
    )  # fmt: skip
    return ws


def test_las_cuatro_reglas_desde_la_base(negocio):
    alerts = evaluate_workspace(negocio, HOY)
    codes = {a.code for a in alerts}
    assert codes == {
        "margen_bajo_objetivo",
        "costos_variables_crecen",
        "riesgo_caja_fechas",
        "retiro_sin_cobertura",
    }
    riesgo = next(a for a in alerts if a.code == "riesgo_caja_fechas")
    # 12000 + 5000 + 5000 − 500 − 1500 − 4000 = 16000; el alquiler del 20 (20000) no alcanza.
    assert riesgo.data_used["efectivo_hoy"] == "16000.00"
    assert all(a.period_start == datetime.date(2026, 10, 1) for a in alerts)
    # Reevaluar no duplica.
    evaluate_workspace(negocio, HOY)
    assert Alert.objects.for_workspace(negocio).count() == 4


def test_se_resuelven_solas_y_respetan_preferencias(negocio):
    evaluate_workspace(negocio, HOY)
    BusinessGoal.objects.filter(workspace=negocio).update(target_margin_pct=None)
    AlertRule.objects.create(workspace=negocio, code="costos_variables_crecen", enabled=False)
    evaluate_workspace(negocio, HOY)
    estados = dict(Alert.objects.for_workspace(negocio).values_list("code", "status"))
    assert estados["margen_bajo_objetivo"] == "resuelta"
    assert estados["costos_variables_crecen"] == "resuelta"
    assert estados["riesgo_caja_fechas"] == "nueva"


def test_vistas_de_alertas_en_el_negocio(client, user, negocio):
    evaluate_workspace(negocio, HOY)
    client.force_login(user)
    page = client.get(reverse("alerts:index", kwargs={"ws": negocio.pk}))
    assert (
        page.status_code == 200 and "Tus retiros dejaron pagos sin cubrir" in page.content.decode()
    )
    rules = client.get(reverse("alerts:rules", kwargs={"ws": negocio.pk}))
    assert "Costos creciendo más que las ventas" in rules.content.decode()
    data = {
        "margen_bajo_objetivo__enabled": "on",
        "margen_bajo_objetivo__puntos_tolerancia": "2",
        "costos_variables_crecen__diferencia_pct": "20",
        "riesgo_caja_fechas__enabled": "on",
        "retiro_sin_cobertura__enabled": "on",
    }
    client.post(reverse("alerts:rules", kwargs={"ws": negocio.pk}), data)
    regla = AlertRule.objects.get(workspace=negocio, code="costos_variables_crecen")
    assert not regla.enabled and regla.params == {"diferencia_pct": 20}
