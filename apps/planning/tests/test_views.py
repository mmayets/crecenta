import uuid
from datetime import date
from unittest import mock

import pytest
from django.urls import reverse

from apps.personal.tests.data import load_caso_50000
from apps.planning.models import PlanVersion

pytestmark = pytest.mark.django_db
S = PlanVersion.Status


@pytest.fixture(autouse=True)
def hoy():
    with mock.patch("apps.planning.views._today", return_value=date(2026, 10, 10)):
        yield


@pytest.fixture
def logged(client, user, personal_ws):
    load_caso_50000(personal_ws)
    client.force_login(user)
    return client


def url(name, ws, **kw):
    return reverse(f"planning:{name}", kwargs={"ws": ws.pk, **kw})


def generar(client, ws, capture):
    with capture(execute=True):
        response = client.post(url("generate", ws))
    return PlanVersion.objects.for_workspace(ws).latest("created_at"), response


def test_generar_ver_y_aceptar(logged, personal_ws, django_capture_on_commit_callbacks):
    plan, response = generar(logged, personal_ws, django_capture_on_commit_callbacks)
    assert response["Location"] == url("detail", personal_ws, plan_id=plan.pk)
    html = logged.get(response["Location"]).content.decode()
    assert "RD$50,000.00" in html and "RD$3,000.00" in html
    assert "Aceptar" in html and "Explicación automática" in html
    logged.post(url("accept", personal_ws, plan_id=plan.pk))
    plan.refresh_from_db()
    assert plan.status == S.ACEPTADO
    index = logged.get(url("index", personal_ws)).content.decode()
    assert "Plan vigente" in index
    # aceptar de nuevo muestra el error, no falla
    response = logged.post(url("accept", personal_ws, plan_id=plan.pk), follow=True)
    assert "ya está aceptado" in response.content.decode()


def test_mientras_se_genera_la_pagina_se_actualiza(logged, personal_ws):
    logged.post(url("generate", personal_ws))  # sin ejecutar la tarea
    plan = PlanVersion.objects.for_workspace(personal_ws).get()
    html = logged.get(url("detail", personal_ws, plan_id=plan.pk), HTTP_HX_REQUEST="true").content
    assert b'hx-trigger="every 2s"' in html
    assert b"<html" not in html  # parcial
    assert "propuesta pendiente" in logged.get(url("index", personal_ws)).content.decode()


def test_descartar(logged, personal_ws, django_capture_on_commit_callbacks):
    plan, _ = generar(logged, personal_ws, django_capture_on_commit_callbacks)
    response = logged.post(url("discard", personal_ws, plan_id=plan.pk))
    assert response["Location"] == url("index", personal_ws)
    plan.refresh_from_db()
    assert plan.status == S.DESCARTADO
    response = logged.post(url("discard", personal_ws, plan_id=plan.pk), follow=True)
    assert "descartado" in response.content.decode()


def test_editar(logged, personal_ws, django_capture_on_commit_callbacks):
    plan, _ = generar(logged, personal_ws, django_capture_on_commit_callbacks)
    form = logged.get(url("edit", personal_ws, plan_id=plan.pk)).content.decode()
    assert "Alimentación" in form and "Aporte a Fondo de emergencia" in form
    snapshot = plan.inputs_snapshot
    data = {
        "alternativa": "",
        "ocio_deseado": "4000",
        "reserva_pct": "10",
        **{f"esencial_{e['ref']}": e["monto"] for e in snapshot["esenciales"]},
        **{f"ahorro_{g['ref']}": "8000" for g in snapshot["ahorro"]},
    }
    with django_capture_on_commit_callbacks(execute=True):
        response = logged.post(url("edit", personal_ws, plan_id=plan.pk), data)
    nuevo = PlanVersion.objects.for_workspace(personal_ws).latest("created_at")
    assert response["Location"] == url("detail", personal_ws, plan_id=nuevo.pk)
    assert nuevo.computed["totales"]["ahorro"] == "8000.00"
    assert nuevo.computed["totales"]["discrecional"] == "4000.00"
    # editar una versión reemplazada redirige con aviso
    response = logged.get(url("edit", personal_ws, plan_id=plan.pk))
    assert response.status_code == 302


def test_editar_con_alternativa_que_no_aplica(
    logged, personal_ws, django_capture_on_commit_callbacks
):
    plan, _ = generar(logged, personal_ws, django_capture_on_commit_callbacks)
    plan.computed["alternativas"] = [{"codigo": "bajar_ahorro", "nombre": "Bajar"}]
    plan.save()
    snapshot = plan.inputs_snapshot
    data = {
        "alternativa": "bajar_ahorro",
        "reserva_pct": "10",
        **{f"esencial_{e['ref']}": e["monto"] for e in snapshot["esenciales"]},
        **{f"ahorro_{g['ref']}": g["aporte"] for g in snapshot["ahorro"]},
    }
    response = logged.post(url("edit", personal_ws, plan_id=plan.pk), data)
    assert response.status_code == 200
    assert "no aplica" in response.content.decode()


def test_comparar(logged, personal_ws, django_capture_on_commit_callbacks):
    a, _ = generar(logged, personal_ws, django_capture_on_commit_callbacks)
    b, _ = generar(logged, personal_ws, django_capture_on_commit_callbacks)
    html = logged.get(url("compare", personal_ws), {"a": a.pk, "b": b.pk}).content.decode()
    assert "Ingreso del período" in html
    assert logged.get(url("compare", personal_ws), {"a": "x", "b": uuid.uuid4()}).status_code == 404


def test_plan_de_otro_espacio_da_404(
    logged, personal_ws, other_ws, other_user, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        from apps.planning.services.generate import request_personal_plan

        ajeno = request_personal_plan(other_ws, other_user, date(2026, 10, 10))
    assert logged.get(url("detail", personal_ws, plan_id=ajeno.pk)).status_code == 404
    assert logged.post(url("accept", personal_ws, plan_id=ajeno.pk)).status_code == 404


def test_espacio_de_negocio_no_tiene_plan_personal(logged, business_ws):
    assert logged.get(url("index", business_ws)).status_code == 404


def test_aplicar_alternativa(client, user, personal_ws, django_capture_on_commit_callbacks):
    load_caso_50000(personal_ws, salary="40000")
    client.force_login(user)
    plan, _ = generar(client, personal_ws, django_capture_on_commit_callbacks)
    html = client.get(url("detail", personal_ws, plan_id=plan.pk)).content.decode()
    assert "Aplicar esta alternativa" in html and "Fechas en que no alcanza" in html
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            url("apply", personal_ws, plan_id=plan.pk), {"alternativa": "bajar_ahorro"}
        )
    nuevo = PlanVersion.objects.for_workspace(personal_ws).latest("created_at")
    assert response["Location"] == url("detail", personal_ws, plan_id=nuevo.pk)
    assert nuevo.plan_status == "ajustado"
    response = client.post(
        url("apply", personal_ws, plan_id=nuevo.pk), {"alternativa": "inventada"}, follow=True
    )
    assert "no aplica" in response.content.decode()
    response = client.post(
        url("apply", personal_ws, plan_id=plan.pk), {"alternativa": "bajar_ahorro"}, follow=True
    )
    assert "reemplazado" in response.content.decode()
