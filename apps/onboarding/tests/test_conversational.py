import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.ai.providers import FakeProvider, ProviderError
from apps.ai.schemas import OnboardingExtraction
from apps.ledger.models import Account, Category
from apps.onboarding.services.conversational import to_initial
from apps.onboarding.services.steps import get_state
from apps.onboarding.views import _confirmation_forms
from apps.personal.models import (
    Commitment,
    EssentialEstimate,
    IncomeSource,
    PersonalProfile,
    SavingsGoal,
)

pytestmark = pytest.mark.django_db

EXTRACCION = {
    "ingresos": [
        {"nombre": "Salario", "monto": "50000", "frecuencia": "mensual", "dias_cobro": [30]}
    ],
    "cuentas": [
        {"nombre": "Efectivo", "tipo": "efectivo", "saldo": "2000"},
        {"nombre": "Banco Popular", "tipo": "banco", "saldo": "15000"},
    ],
    "compromisos": [
        {
            "nombre": "Alquiler",
            "monto": "18000",
            "frecuencia": "mensual",
            "dia_vencimiento": 5,
            "categoria": "Alquiler o hipoteca",
        },
        {
            "nombre": "Luz",
            "monto": "2500",
            "frecuencia": "mensual",
            "dia_vencimiento": None,
            "categoria": "Electricidad",
        },
    ],
    "esenciales": [
        {"categoria": "Alimentación", "monto": "12000"},
        {"categoria": "comida", "monto": "1000"},
    ],
    "deudas": [],
    "metas_ahorro": [
        {"proposito": "Fondo de emergencia", "aporte": "5000", "frecuencia": "mensual"}
    ],
    "ocio_deseado": "3000",
    "campos_dudosos": ["compromisos.1.dia_vencimiento", "ingresos.0.frecuencia", "x.y", "deudas.9"],
}


@pytest.fixture
def logged(client, user):
    user.set_ai_consent(True)
    client.force_login(user)
    return client


def url(ws, name):
    return reverse(f"onboarding:{name}", kwargs={"ws": ws.pk})


def post_data(workspace, **overrides):
    """Datos de la tabla de confirmación tal como los enviaría el navegador sin cambios."""
    initial = to_initial(workspace, OnboardingExtraction.model_validate(EXTRACCION))
    formsets, essentials = _confirmation_forms(workspace, initial)
    data = {}
    for formset in formsets.values():
        data.update({k: str(v) for k, v in formset.management_form.initial.items()})
        data = {
            **data,
            **{f"{formset.prefix}-{k}": v for k, v in formset.management_form.initial.items()},
        }
        for form in formset.forms:
            for name, field in form.fields.items():
                value = form.initial.get(name, field.initial)
                if value is None or name == "DELETE":
                    continue
                if isinstance(value, bool):
                    if value:
                        data[form.add_prefix(name)] = "on"
                    continue
                data[form.add_prefix(name)] = str(value)
    for name in essentials.fields:
        if essentials.initial.get(name) is not None:
            data[name] = str(essentials.initial[name])
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not None}


def test_extrae_confirma_y_guarda(logged, personal_ws):
    FakeProvider.queue(EXTRACCION)
    response = logged.post(url(personal_ws, "conversation"), {"texto": "cobro 50 mil el 30…"})
    assert response["Location"] == url(personal_ws, "confirm")
    assert not IncomeSource.objects.exists()  # nada se guarda antes de confirmar
    assert get_state(personal_ws).pending_extraction["ingresos"][0]["monto"] == "50000"

    html = logged.get(url(personal_ws, "confirm")).content.decode()
    assert "¿Entendimos bien?" in html
    assert "No supimos" not in html  # "comida" se reconoce como Alimentación
    assert 'name="compromisos-1-due_day"' in html and 'class="dudoso"' in html

    response = logged.post(url(personal_ws, "confirm"), post_data(personal_ws))
    assert response.status_code == 400  # falta el día de la luz (dudoso)
    response = logged.post(
        url(personal_ws, "confirm"), post_data(personal_ws, **{"compromisos-1-due_day": "15"})
    )
    assert response.status_code == 302

    income = IncomeSource.objects.for_workspace(personal_ws).get()
    assert (income.net_amount, income.pay_days) == (50000, [30])
    assert Commitment.objects.for_workspace(personal_ws).count() == 2
    alimentacion = Category.objects.for_workspace(personal_ws).get(name="Alimentación")
    assert (
        EssentialEstimate.objects.for_workspace(personal_ws).get(category=alimentacion).amount
        == 13000
    )
    efectivo = Account.objects.for_workspace(personal_ws).get(name="Efectivo")
    assert efectivo.opening_balance == 2000  # actualiza la cuenta existente, no la duplica
    assert Account.objects.for_workspace(personal_ws).count() == 2
    assert SavingsGoal.objects.for_workspace(personal_ws).get().contribution_amount == 5000
    assert PersonalProfile.objects.get(workspace=personal_ws).discretionary_wish == 3000
    state = get_state(personal_ws)
    assert state.pending_extraction is None
    assert {"ingresos", "compromisos", "esenciales", "cuentas", "ahorro"} <= set(
        state.answered_steps
    )


def test_quitar_una_fila(logged, personal_ws):
    FakeProvider.queue(EXTRACCION)
    logged.post(url(personal_ws, "conversation"), {"texto": "x"})
    data = post_data(personal_ws, **{"compromisos-1-DELETE": "on", "metas_ahorro": None})
    assert logged.post(url(personal_ws, "confirm"), data).status_code == 302
    assert list(Commitment.objects.values_list("name", flat=True)) == ["Alquiler"]


def test_sin_consentimiento_sugiere_el_formulario(client, user, personal_ws):
    client.force_login(user)
    response = client.post(url(personal_ws, "conversation"), {"texto": "cobro 50 mil"})
    assert response.status_code == 200
    assert "paso a paso" in response.content.decode()
    assert get_state(personal_ws).pending_extraction is None


def test_confirmar_sin_extraccion_redirige(logged, personal_ws):
    assert logged.get(url(personal_ws, "confirm"))["Location"] == url(personal_ws, "conversation")
    assert "Cuéntanos" in logged.get(url(personal_ws, "conversation")).content.decode()


def test_mapeo_inicial(personal_ws):
    ext = OnboardingExtraction.model_validate(
        {
            "ingresos": [
                {"monto": "1200", "frecuencia": "semanal", "dias_cobro": [4]},
                {"monto": "8000", "frecuencia": "variable"},
            ],
            "compromisos": [{"nombre": "Gimnasio", "monto": "1500"}],
            "deudas": [{"nombre": "Tarjeta", "cuota": "3000"}],
            "esenciales": [{"categoria": "Inventada", "monto": "5"}],
        }
    )
    initial = to_initial(personal_ws, ext)
    assert initial["ingresos"][0]["dia_semana"] == 4
    assert {
        "ingresos-1-dia_1",
        "compromisos-0-category",
        "compromisos-0-due_day",
        "deudas-0-due_day",
    } <= initial["dudosos"]
    assert initial["esenciales"] == {}
    assert initial["sin_categoria"] == [{"nombre": "Inventada", "monto": 5}]


def test_voz(logged, client, personal_ws, user):
    audio = SimpleUploadedFile("nota.webm", b"\x1a\x45\xdf\xa3", content_type="audio/webm")
    FakeProvider.queue("cobro cincuenta mil")
    response = logged.post(url(personal_ws, "voice"), {"audio": audio})
    assert response.json() == {"texto": "cobro cincuenta mil"}
    texto = SimpleUploadedFile("x.txt", b"hola", content_type="text/plain")
    assert logged.post(url(personal_ws, "voice"), {"audio": texto}).status_code == 400
    FakeProvider.queue(ProviderError("x"))
    audio.seek(0)
    assert logged.post(url(personal_ws, "voice"), {"audio": audio}).status_code == 503


def test_voz_demasiado_larga(logged, personal_ws, monkeypatch):
    from apps.onboarding import views

    monkeypatch.setattr(views, "MAX_AUDIO_BYTES", 2)
    audio = SimpleUploadedFile("nota.webm", b"123", content_type="audio/webm")
    assert logged.post(url(personal_ws, "voice"), {"audio": audio}).status_code == 400
