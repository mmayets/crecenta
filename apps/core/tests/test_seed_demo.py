from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from apps.accounts.models import User
from apps.business.models import BusinessProfile, Payable, Product, Receivable, Sale
from apps.business.services.loaders import business_snapshot
from apps.ledger.models import Transaction
from apps.onboarding.services.steps import completeness
from apps.planning.models import BudgetPeriod, PlanVersion
from apps.workspaces.models import Workspace, WorkspaceTransfer

pytestmark = pytest.mark.django_db


def run(*args):
    out = StringIO()
    call_command("seed_demo", *args, stdout=out)
    return out.getvalue()


def test_demo_completa():
    output = run()
    assert "Demo lista" in output and "demo@crecenta.app" in output
    user = User.objects.get(email="demo@crecenta.app")
    assert user.check_password("Demo-Crecenta-2026")
    personal = Workspace.objects.get(owner=user, kind="personal")
    business = Workspace.objects.get(owner=user, kind="business")

    plan = PlanVersion.objects.for_workspace(personal).get(status="aceptado")
    assert plan.plan_status == "viable"
    assert plan.computed["totales"] == {
        "compromiso": "20000.00",
        "deuda": "0.00",
        "esencial": "15000.00",
        "ahorro": "7000.00",
        "discrecional": "5000.00",
        "reserva": "3000.00",
    }
    assert BudgetPeriod.objects.for_workspace(personal).filter(is_active=True).count() == 1
    assert Transaction.objects.for_workspace(personal).filter(kind="ingreso").exists()
    assert completeness(personal).percent == 100

    product = Product.objects.for_workspace(business).get(name="Bizcocho de vainilla (1 lb)")
    assert (product.unit_cost, product.price) == (Decimal("600.00"), Decimal("857.14"))
    assert product.components.count() == 3
    assert str(BusinessProfile.objects.get()) == "Dulces Ana · Repostería"

    # Negocio con indicadores reales (pase lo que pase con la fecha de hoy).
    snapshot = business_snapshot(business, timezone.localdate())
    assert snapshot.indicators.sales > 0 and snapshot.indicators.cogs > 0
    assert Sale.objects.for_workspace(business).filter(payment="credito").exists()
    assert Receivable.objects.for_workspace(business).filter(status="parcial").exists()
    assert Payable.objects.for_workspace(business).count() == 2  # harina y refrescos a crédito
    assert WorkspaceTransfer.objects.get().to_workspace == personal
    business_plan = PlanVersion.objects.for_workspace(business).get()
    assert business_plan.status == "propuesta" and business_plan.plan_status == "ajustado"
    assert business_plan.computed["resultado"] == "12528.40"
    # Fase 3: inventario real del refresco (inicial + compras − ventas − merma).
    refresco = Product.objects.get(workspace=business, name="Refresco de 2 litros")
    assert refresco.stock == 40 and refresco.average_cost == Decimal("74.3692")
    assert snapshot.indicators.shrinkage == Decimal("148.74")
    assert snapshot.indicators.inventory_value == Decimal("2974.77")
    assert "posponer_retiro" not in [a["codigo"] for a in business_plan.computed["alternativas"]]
    assert completeness(business).percent == 100


def test_idempotente_y_reset():
    run()
    assert "ya existe" in run()
    first = User.objects.get(email="demo@crecenta.app").pk
    run("--reset")
    assert User.objects.get(email="demo@crecenta.app").pk != first
    assert Workspace.objects.filter(owner__email="demo@crecenta.app").count() == 2


def test_no_borra_una_cuenta_real(user):
    with pytest.raises(CommandError):
        run("--email", user.email, "--reset")
    assert User.objects.filter(pk=user.pk).exists()


def test_preparar_e2e():
    import json

    out = StringIO()
    call_command("preparar_e2e", stdout=out)
    data = json.loads(out.getvalue())
    assert Workspace.objects.get(pk=data["ws"]).owner.email == data["email"]
