from decimal import Decimal

import pytest
from django.urls import reverse

from apps.ledger.models import Account, Category
from apps.onboarding.services.steps import completeness, get_state
from apps.personal.models import (
    Commitment,
    EssentialEstimate,
    IncomeSource,
    PersonalProfile,
    Preference,
    SavingsGoal,
)
from apps.planning.models import PlanVersion

pytestmark = pytest.mark.django_db


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


def cat(ws, name):
    return Category.objects.for_workspace(ws).get(name=name).pk


def post_ingresos(client, ws, **row):
    data = {
        **management("ingresos", 1),
        "ingresos-0-name": "Salario",
        "ingresos-0-net_amount": "50000",
        "ingresos-0-frequency": "mensual",
        "ingresos-0-dia_1": "1",
        **{f"ingresos-0-{k}": v for k, v in row.items()},
    }
    return client.post(url(ws, "ingresos"), data)


def test_onboarding_minimo_hasta_el_plan(logged, personal_ws, django_capture_on_commit_callbacks):
    """Criterio de aceptación: con 3 pasos (ingresos, compromisos, esenciales) hay un plan."""
    assert logged.get(url(personal_ws, name="index"))["Location"] == url(personal_ws, "ingresos")
    response = post_ingresos(logged, personal_ws)
    assert response["Location"] == url(personal_ws, "compromisos")

    compromisos = {
        **management("compromisos", 2),
        "compromisos-0-name": "Alquiler",
        "compromisos-0-category": cat(personal_ws, "Alquiler o hipoteca"),
        "compromisos-0-amount": "15000",
        "compromisos-0-frequency": "mensual",
        "compromisos-0-due_day": "5",
        "compromisos-0-is_fixed": "on",
        "compromisos-1-name": "Luz",
        "compromisos-1-category": cat(personal_ws, "Electricidad"),
        "compromisos-1-amount": "5000",
        "compromisos-1-frequency": "mensual",
        "compromisos-1-due_day": "15",
    }
    assert logged.post(url(personal_ws, "compromisos"), compromisos)["Location"] == url(
        personal_ws, "esenciales"
    )
    esenciales = {
        f"cat_{cat(personal_ws, 'Alimentación')}": "10000",
        f"cat_{cat(personal_ws, 'Transporte y combustible')}": "5000",
    }
    assert logged.post(url(personal_ws, "esenciales"), esenciales)["Location"] == url(
        personal_ws, "ahorro"
    )
    progress = completeness(personal_ws)
    assert progress.minimum_ready
    html = logged.get(url(personal_ws, "ahorro")).content.decode()
    assert "Ya puedo generar mi plan" in html and "Omitir por ahora" in html

    with django_capture_on_commit_callbacks(execute=True):
        response = logged.post(url(personal_ws, name="done"))
    plan = PlanVersion.objects.for_workspace(personal_ws).get()
    assert response["Location"] == reverse(
        "planning:detail", kwargs={"ws": personal_ws.pk, "plan_id": plan.pk}
    )
    plan.refresh_from_db()
    assert plan.plan_status in {"viable", "ajustado", "no_viable"}
    assert plan.plan_status == "viable"
    assert plan.status == "propuesta"
    assert get_state(personal_ws).finished_at is not None


@pytest.mark.parametrize(
    ("row", "field"),
    [
        ({"frequency": "quincenal", "dia_1": "15"}, "dia_2"),
        ({"dia_1": ""}, "dia_1"),
        ({"frequency": "semanal", "dia_1": ""}, "dia_semana"),
        ({"net_amount": "-1"}, "net_amount"),
    ],
)
def test_validaciones_de_ingresos(logged, personal_ws, row, field):
    response = post_ingresos(logged, personal_ws, **row)
    assert response.status_code == 400
    assert field in response.context["form"].forms[0].errors
    assert not IncomeSource.objects.exists()


def test_ingreso_quincenal_y_semanal(logged, personal_ws):
    post_ingresos(
        logged, personal_ws, frequency="quincenal", dia_1="15", dia_2="30", net_amount="25000"
    )
    income = IncomeSource.objects.for_workspace(personal_ws).get()
    assert income.pay_days == [15, 30]
    html = logged.get(url(personal_ws, "ingresos")).content.decode()
    assert 'value="30"' in html  # precarga lo guardado
    data = {
        **management("ingresos", 2, initial=1),
        "ingresos-0-id": str(income.pk),
        "ingresos-0-name": "Salario",
        "ingresos-0-net_amount": "25000",
        "ingresos-0-frequency": "quincenal",
        "ingresos-0-dia_1": "15",
        "ingresos-0-dia_2": "30",
        "ingresos-0-DELETE": "on",
        "ingresos-1-name": "Chiripa",
        "ingresos-1-net_amount": "1500",
        "ingresos-1-frequency": "semanal",
        "ingresos-1-dia_semana": "5",
    }
    logged.post(url(personal_ws, "ingresos"), data)
    (only,) = IncomeSource.objects.for_workspace(personal_ws)
    assert (only.name, only.pay_days) == ("Chiripa", [5])
    assert "selected" in logged.get(url(personal_ws, "ingresos")).content.decode()


def test_guardar_y_agregar_otro(logged, personal_ws):
    response = post_ingresos(logged, personal_ws, accion="quedarse")
    assert response.status_code == 302
    data = {
        **management("ingresos", 1),
        "accion": "quedarse",
        "ingresos-0-name": "x",
        "ingresos-0-net_amount": "1",
        "ingresos-0-frequency": "mensual",
        "ingresos-0-dia_1": "1",
    }
    assert logged.post(url(personal_ws, "ingresos"), data)["Location"] == url(
        personal_ws, "ingresos"
    )


def test_omitir_solo_pasos_opcionales(logged, personal_ws):
    response = logged.post(url(personal_ws, "deudas"), {"accion": "omitir"})
    assert response["Location"] == url(personal_ws, "preferencias")
    assert "deudas" in get_state(personal_ws).skipped_steps
    response = logged.post(url(personal_ws, "esenciales"), {"accion": "omitir"})
    assert response.status_code == 302  # se guarda vacío: el paso se responde, no se omite
    assert "esenciales" in get_state(personal_ws).answered_steps
    response = logged.post(url(personal_ws, "preferencias"), {"accion": "omitir"})
    assert response["Location"] == url(personal_ws, name="done")


def test_esenciales_y_preferencias(logged, personal_ws):
    alimentacion = cat(personal_ws, "Alimentación")
    logged.post(url(personal_ws, "esenciales"), {f"cat_{alimentacion}": "12000"})
    assert EssentialEstimate.objects.for_workspace(personal_ws).get().amount == 12000
    logged.post(url(personal_ws, "esenciales"), {f"cat_{alimentacion}": ""})
    assert not EssentialEstimate.objects.exists()

    logged.post(
        url(personal_ws, "preferencias"),
        {"ocio_deseado": "4000", "reserva_pct": "5", f"pref_{alimentacion}": "reducible"},
    )
    profile = PersonalProfile.objects.get(workspace=personal_ws)
    assert (profile.discretionary_wish, profile.reserve_pct) == (4000, Decimal("0.05"))
    assert Preference.objects.for_workspace(personal_ws).get().priority == "reducible"
    html = logged.get(url(personal_ws, "preferencias")).content.decode()
    assert 'value="4000.00"' in html
    logged.post(url(personal_ws, "preferencias"), {"reserva_pct": "10"})
    assert not Preference.objects.exists()


def test_cuentas_y_ahorro(logged, personal_ws):
    efectivo = Account.objects.for_workspace(personal_ws).get()
    data = {
        **management("cuentas", 2, initial=1),
        "cuentas-0-id": str(efectivo.pk),
        "cuentas-0-name": "Efectivo",
        "cuentas-0-type": "efectivo",
        "cuentas-0-opening_balance": "2500",
        "cuentas-1-name": "Ahorros Banreservas",
        "cuentas-1-type": "banco",
        "cuentas-1-opening_balance": "40000",
        "cuentas-1-is_savings": "on",
    }
    assert logged.post(url(personal_ws, "cuentas"), data).status_code == 302
    efectivo.refresh_from_db()
    assert efectivo.opening_balance == 2500
    assert Account.objects.for_workspace(personal_ws).get(is_savings=True).currency == "DOP"

    ahorro = {
        **management("ahorro", 1),
        "ahorro-0-purpose": "Viaje",
        "ahorro-0-contribution_amount": "100",
        "ahorro-0-contribution_frequency": "diaria",
        "ahorro-0-daily_mode": "dias_seleccionados",
    }
    response = logged.post(url(personal_ws, "ahorro"), ahorro)
    assert response.status_code == 400  # faltan los días seleccionados
    ahorro["ahorro-0-selected_weekdays"] = ["0", "2", "4"]
    assert logged.post(url(personal_ws, "ahorro"), ahorro).status_code == 302
    assert SavingsGoal.objects.for_workspace(personal_ws).get().selected_weekdays == [0, 2, 4]


def test_compromiso_con_categoria_ajena(logged, personal_ws, other_ws):
    data = {
        **management("compromisos", 1),
        "compromisos-0-name": "X",
        "compromisos-0-category": cat(other_ws, "Agua"),
        "compromisos-0-amount": "10",
        "compromisos-0-frequency": "mensual",
        "compromisos-0-due_day": "5",
    }
    assert logged.post(url(personal_ws, "compromisos"), data).status_code == 400
    assert not Commitment.objects.exists()


def test_resumen_y_requisitos(logged, personal_ws):
    html = logged.get(url(personal_ws, name="done")).content.decode()
    assert "Faltan datos" in html and "Sin ingresos no podemos calcular" in html
    response = logged.post(url(personal_ws, name="done"), follow=True)
    assert "Completa ingresos" in response.content.decode()
    state = get_state(personal_ws)
    for key in [
        "ingresos",
        "compromisos",
        "esenciales",
        "ahorro",
        "cuentas",
        "deudas",
        "preferencias",
    ]:
        state.mark(key, skipped=key not in ["ingresos", "compromisos", "esenciales"])
    state.save()
    assert logged.get(url(personal_ws, name="index"))["Location"] == url(personal_ws, name="done")


def test_paso_inexistente_y_negocio(logged, personal_ws, business_ws):
    assert logged.get(url(personal_ws, "inventado")).status_code == 404
    # El negocio tiene su propia bienvenida (paso B8).
    assert logged.get(url(business_ws, name="index"))["Location"] == url(business_ws, "perfil")
    assert logged.get(url(business_ws, "ingresos")).status_code == 404
