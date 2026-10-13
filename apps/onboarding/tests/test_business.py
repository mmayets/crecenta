from decimal import Decimal

import pytest
from django.urls import reverse

from apps.ai.providers import FakeProvider
from apps.ai.schemas import BusinessOnboardingExtraction
from apps.business.models import BusinessGoal, BusinessProfile, OperatingExpense, Product
from apps.ledger.models import Account, Category
from apps.onboarding.business_views import _confirmation_forms
from apps.onboarding.services.business_conversational import to_business_initial
from apps.onboarding.services.steps import completeness, get_state
from apps.planning.models import PlanVersion

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture
def logged(client, user):
    client.force_login(user)
    return client


def url(ws, step=None, name="step"):
    if step:
        return reverse(f"onboarding:{name}", kwargs={"ws": ws.pk, "step": step})
    return reverse(f"onboarding:{name}", kwargs={"ws": ws.pk})


def management(prefix, total, initial=0):
    return {
        f"{prefix}-TOTAL_FORMS": str(total),
        f"{prefix}-INITIAL_FORMS": str(initial),
        f"{prefix}-MIN_NUM_FORMS": "0",
        f"{prefix}-MAX_NUM_FORMS": "1000",
    }


def test_paso_a_paso_hasta_el_primer_plan(logged, business_ws, django_capture_on_commit_callbacks):
    ws = business_ws
    assert logged.get(url(ws, name="index"))["Location"] == url(ws, "perfil")
    html = logged.get(url(ws, "perfil")).content.decode()
    assert "¿A qué se dedica tu negocio?" in html and "Prefiero contarlo con mis palabras" in html
    # Los datos mínimos no están: no se puede generar el plan.
    response = logged.post(url(ws, name="done"))
    assert response["Location"] == url(ws, name="index")

    response = logged.post(
        url(ws, "perfil"),
        {"activity": "Repostería", "model": "productos", "cobra_itbis": "on", "tasa_pct": "18"},
    )
    assert response["Location"] == url(ws, "productos")
    profile = BusinessProfile.objects.get(workspace=ws)
    assert profile.tax_rate_itbis == D("0.180") and not profile.prices_include_tax

    productos = {
        **management("productos", 2),
        "productos-0-name": "Bizcocho",
        "productos-0-price": "857.14",
        "productos-0-unit_cost": "600",
        "productos-0-expected_monthly_units": "40",
        "productos-1-name": "",
    }
    assert logged.post(url(ws, "productos"), productos)["Location"] == url(ws, "gastos")
    # Nombre repetido: error en el formulario.
    repetido = {**management("productos", 2, 1), "productos-0-id": str(Product.objects.get().pk),
                "productos-0-name": "Bizcocho", "productos-0-price": "857.14",
                "productos-0-unit_cost": "600", "productos-1-name": "bizcocho",
                "productos-1-price": "1", "productos-1-unit_cost": "1"}  # fmt: skip
    assert logged.post(url(ws, "productos"), repetido).status_code == 400

    alquiler = Category.objects.get(workspace=ws, name="Alquiler del local")
    gastos = {
        **management("gastos", 1),
        "gastos-0-name": "Alquiler",
        "gastos-0-category": str(alquiler.pk),
        "gastos-0-amount": "8000",
        "gastos-0-frequency": "mensual",
        "gastos-0-due_day": "5",
    }
    assert logged.post(url(ws, "gastos"), gastos)["Location"] == url(ws, "efectivo")
    assert logged.post(url(ws, "efectivo"), {"accion": "omitir"})["Location"] == url(
        ws, "objetivos"
    )
    metas = {"margen_pct": "30", "target_profit": "5000", "planned_owner_draw": "2000"}
    assert logged.post(url(ws, "objetivos"), metas)["Location"] == url(ws, name="done")
    goal = BusinessGoal.objects.get(workspace=ws)
    assert goal.target_margin_pct == D("0.3000") and goal.cash_reserve == 0

    progress = completeness(ws)
    assert progress.minimum_ready and progress.percent == 90  # falta el efectivo
    assert "Generar el plan de mi negocio" in logged.get(url(ws, name="done")).content.decode()
    with django_capture_on_commit_callbacks(execute=True):
        response = logged.post(url(ws, name="done"))
    plan = PlanVersion.objects.get(workspace=ws)
    assert plan.kind == PlanVersion.Kind.BUSINESS and plan.status == PlanVersion.Status.PROPUESTA
    assert response["Location"] == reverse(
        "planning:detail", kwargs={"ws": ws.pk, "plan_id": plan.pk}
    )
    assert get_state(ws).finished_at is not None
    # Paso a paso: editar lo ya guardado precarga los valores.
    html = logged.get(url(ws, "perfil")).content.decode()
    assert 'value="Repostería"' in html
    assert 'value="30.0000"' in logged.get(url(ws, "objetivos")).content.decode()


def test_pasos_obligatorios_no_se_omiten(logged, business_ws):
    response = logged.post(url(business_ws, "productos"), {"accion": "omitir"})
    assert response.status_code == 400
    assert logged.post(
        url(business_ws, "productos"),
        {
            **management("productos", 1),
            "accion": "quedarse",
            "productos-0-name": "Torta",
            "productos-0-price": "1000",
            "productos-0-unit_cost": "500",
        },  # fmt: skip
    )["Location"] == url(business_ws, "productos")
    assert logged.get(url(business_ws, "inventado")).status_code == 404


EXTRACCION = {
    "actividad": "Repostería por encargo",
    "cobra_itbis": False,
    "productos": [
        {"nombre": "Bizcocho", "precio": "857.14", "costo": "600", "unidades_mes": "40"},
        {"nombre": "Cupcake", "precio": "100", "costo": None, "unidades_mes": None},
    ],
    "gastos": [
        {"nombre": "Alquiler del local", "monto": "8000", "dia": 5},
        {"nombre": "Luz", "monto": "1500", "dia": None},
    ],
    "efectivo": "15000",
    "margen_objetivo_pct": "30",
    "retiro_mensual": "10000",
    "campos_dudosos": ["productos.0.unidades_mes", "otro.x", "gastos.0.inexistente"],
}


def post_data(workspace, **overrides):
    """Datos de la confirmación tal como los enviaría el navegador sin cambios."""
    initial = to_business_initial(
        workspace, BusinessOnboardingExtraction.model_validate(EXTRACCION)
    )
    profile, formsets, cash, goals = _confirmation_forms(workspace, initial)
    data: dict[str, str] = {}

    def put(form, name, value):
        if value is None or name == "DELETE":
            return
        if isinstance(value, bool):
            if value:
                data[form.add_prefix(name)] = "on"
            return
        data[form.add_prefix(name)] = str(value)

    for formset in formsets.values():
        data.update(
            {f"{formset.prefix}-{k}": str(v) for k, v in formset.management_form.initial.items()}
        )
        for form in formset.forms:
            for name, field in form.fields.items():
                put(form, name, form.initial.get(name, field.initial))
    for form in (profile, cash, goals):
        for name, field in form.fields.items():
            put(form, name, form.initial.get(name, field.initial))
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not None}


def test_conversacional_extrae_confirma_y_genera_plan(
    client, user, business_ws, django_capture_on_commit_callbacks
):
    ws = business_ws
    user.set_ai_consent(True)
    client.force_login(user)
    FakeProvider.queue(EXTRACCION)
    html = client.get(url(ws, name="conversation")).content.decode()
    assert "Cuéntanos de tu negocio" in html
    response = client.post(url(ws, name="conversation"), {"texto": "Hago bizcochos…"})
    assert response["Location"] == url(ws, name="confirm")
    assert not Product.objects.exists()  # nada se guarda antes de confirmar
    prompt = FakeProvider.calls[0]["system"]
    assert "pequeño negocio" in prompt

    html = client.get(url(ws, name="confirm")).content.decode()
    assert "¿Entendimos bien?" in html and 'class="dudoso"' in html
    sin_nombre = post_data(ws, **{"productos-0-name": ""})
    assert client.post(url(ws, name="confirm"), sin_nombre).status_code == 400
    response = client.post(url(ws, name="confirm"), post_data(ws, **{"gastos-1-due_day": "15"}))
    assert response.status_code == 302

    assert BusinessProfile.objects.get(workspace=ws).tax_rate_itbis == 0
    cupcake = Product.objects.get(workspace=ws, name="Cupcake")
    assert cupcake.unit_cost == 0 and cupcake.expected_monthly_units is None
    alquiler = OperatingExpense.objects.get(workspace=ws, name="Alquiler del local")
    assert alquiler.category.name == "Alquiler del local"
    assert Account.objects.get(workspace=ws, name="Efectivo").opening_balance == D("15000")
    goal = BusinessGoal.objects.get(workspace=ws)
    assert goal.target_margin_pct == D("0.3000") and goal.planned_owner_draw == D("10000")
    state = get_state(ws)
    assert state.pending_extraction is None
    assert set(state.answered_steps) == {"perfil", "productos", "gastos", "efectivo", "objetivos"}

    with django_capture_on_commit_callbacks(execute=True):
        client.post(url(ws, name="done"))
    plan = PlanVersion.objects.get(workspace=ws)
    # Al cupcake le faltan unidades y costo: el plan lo dice.
    assert [m["campo"] for m in plan.missing_data][:2] == ["unidades", "costos"]
    assert plan.computed["retiro_planeado"] == "10000.00"


def test_mapeo_inicial_y_casos_borde(business_ws, user):
    ext = BusinessOnboardingExtraction.model_validate(
        {"productos": [{"nombre": "Corte", "precio": "500", "es_servicio": True, "minutos": 45}]}
    )
    initial = to_business_initial(business_ws, ext)
    assert initial["perfil"] == {"model": "servicios", "cobra_itbis": False, "tasa_pct": D("18")}
    assert {"productos-0-unit_cost", "productos-0-expected_monthly_units"} <= initial["dudosos"]
    vacio = to_business_initial(business_ws, BusinessOnboardingExtraction())
    assert vacio["perfil"]["model"] == "productos" and vacio["efectivo"] is None


def test_confirmar_sin_extraccion_y_sin_consentimiento(logged, business_ws):
    assert logged.get(url(business_ws, name="confirm"))["Location"] == url(
        business_ws, name="conversation"
    )
    response = logged.post(url(business_ws, name="conversation"), {"texto": "vendo empanadas"})
    assert response.status_code == 200 and "paso a paso" in response.content.decode()


def test_efectivo_sin_cuentas_crea_la_cuenta(business_ws):
    from apps.onboarding.business_views import _save_cash

    Account.objects.filter(workspace=business_ws).delete()
    _save_cash(business_ws, D("500"))
    assert Account.objects.get(workspace=business_ws).opening_balance == D("500")
    _save_cash(business_ws, D("700"))
    assert Account.objects.get(workspace=business_ws).opening_balance == D("700")
