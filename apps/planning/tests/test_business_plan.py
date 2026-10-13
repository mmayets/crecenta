import datetime
import json
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.ai.providers import FakeProvider
from apps.ai.schemas import PlanNarrative
from apps.ai.services.guards import verify_narrative
from apps.business.models import BusinessGoal, CostComponent, OperatingExpense, Product
from apps.business.services.loaders import load_business_plan_inputs
from apps.business.services.sales import SaleData, SaleLineData, register_sale
from apps.ledger.models import Account
from apps.personal.services.serialize import strip_refs
from apps.planning.models import BudgetPeriod, PlanVersion
from apps.planning.services.generate import request_business_plan
from apps.planning.services.lifecycle import accept_plan, compare_plans, edit_plan

pytestmark = pytest.mark.django_db
D = Decimal
HOY = datetime.date(2026, 10, 1)


@pytest.fixture
def negocio(business_ws, user):
    ws = business_ws
    caja = Account.objects.get(workspace=ws)
    caja.opening_balance = D("15000")
    caja.save()
    biz = Product.objects.create(
        workspace=ws, name="Bizcocho", price=D("857.14"), unit_cost=D("0"),
        expected_monthly_units=D("40"),
    )  # fmt: skip
    CostComponent.objects.create(product=biz, name="Materiales", type="materia", amount=D("600"))
    cup = Product.objects.create(workspace=ws, name="Cupcake", price=D("100"), unit_cost=D("75"))
    # Sin unidades esperadas: se estiman con lo vendido el mes anterior.
    septiembre = datetime.date(2026, 9, 15)
    register_sale(
        ws, user, SaleData(date=septiembre, lines=[SaleLineData(cup, D("150"))], account=caja)
    )
    OperatingExpense.objects.create(workspace=ws, name="Alquiler", amount=D("8000"), due_day=5)
    OperatingExpense.objects.create(
        workspace=ws, name="Publicidad", amount=D("2500"), due_day=20, is_reducible=True
    )
    BusinessGoal.objects.create(
        workspace=ws, target_margin_pct=D("0.30"), target_profit=D("5000"),
        planned_owner_draw=D("3000"),
    )  # fmt: skip
    return ws


def generar(ws, user, capture, **kw):
    with capture(execute=True):
        plan = request_business_plan(ws, user, HOY, **kw)
    plan.refresh_from_db()
    return plan


def test_entradas_desde_la_base(negocio):
    inputs = load_business_plan_inputs(negocio, HOY)
    by_name = {p.name: p for p in inputs.products}
    assert by_name["Bizcocho"].base_cost == D("600") and by_name["Bizcocho"].expected_units == 40
    assert by_name["Cupcake"].expected_units == 150 and by_name["Cupcake"].units_estimated
    assert inputs.cash_now == D("30000.00")  # 15000 + venta de contado de septiembre
    assert inputs.planned_withdrawal == D("3000") and inputs.target_margin == D("0.3000")


def test_entradas_sin_objetivos_ni_perfil(business_ws):
    inputs = load_business_plan_inputs(business_ws, HOY)
    assert inputs.products == () and inputs.target_margin is None and inputs.hours_available is None


def test_plan_de_negocio_con_ia_verificada(negocio, user, django_capture_on_commit_callbacks):
    user.set_ai_consent(True)
    plan = generar(negocio, user, django_capture_on_commit_callbacks)
    assert plan.kind == PlanVersion.Kind.BUSINESS and plan.status == PlanVersion.Status.PROPUESTA
    assert plan.plan_status == "ajustado" and plan.narrative_source == "ia"
    assert plan.computed["ventas"] == "49285.60"
    narrative = PlanNarrative.model_validate(plan.ai_narrative)
    assert verify_narrative(narrative, strip_refs(plan.computed)) == []
    assert "vendería RD$49,285.60" in narrative.resumen
    prompt = FakeProvider.calls[0]["system"] + FakeProvider.calls[0]["user"]
    assert "pequeños negocios" in prompt and '"ref"' not in prompt
    assert any("mes anterior" in a for a in plan.assumptions)


def test_cifras_inventadas_de_la_ia_se_rechazan(negocio, user, django_capture_on_commit_callbacks):
    user.set_ai_consent(True)
    invented = {"resumen": "Vas a ganar RD$99,000.00 este mes.", "estado": "ajustado"}
    FakeProvider.queue(invented, invented)
    plan = generar(negocio, user, django_capture_on_commit_callbacks)
    assert plan.narrative_source == "reglas" and "99,000" not in json.dumps(plan.ai_narrative)


def test_sin_consentimiento_usa_reglas(negocio, user, django_capture_on_commit_callbacks):
    plan = generar(negocio, user, django_capture_on_commit_callbacks)
    assert plan.narrative_source == "reglas"
    assert plan.ai_narrative["resumen"].startswith("Tu plan funciona, pero queda justo.")
    assert plan.ai_narrative["alternativas"]


def test_aceptar_editar_y_comparar(negocio, user, django_capture_on_commit_callbacks):
    plan = generar(negocio, user, django_capture_on_commit_callbacks)
    with django_capture_on_commit_callbacks(execute=True):
        nuevo = edit_plan(plan, user, {"alternativa": "subir_precio", "retiro": "0"}, HOY)
    nuevo.refresh_from_db()
    plan.refresh_from_db()
    assert plan.status == PlanVersion.Status.REEMPLAZADO and nuevo.parent == plan
    # Con el margen objetivo en todos los productos falta poco para la meta de ganancia.
    assert nuevo.plan_status == "ajustado" and nuevo.computed["resultado"] == "4606.60"
    rows = {r.concept: r for r in compare_plans(plan, nuevo)}
    assert rows["Ventas"].difference == D("1071.00")
    assert rows["Retiro del propietario"].difference == D("-3000.00")
    with pytest.raises(ValidationError):
        edit_plan(nuevo, user, {"otra": 1}, HOY)
    accepted = accept_plan(nuevo, user)
    assert accepted.status == PlanVersion.Status.ACEPTADO
    assert not BudgetPeriod.objects.exists()  # el plan de negocio no crea presupuesto personal
