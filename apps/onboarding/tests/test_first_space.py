from decimal import Decimal

import pytest
from django.urls import reverse

from apps.business.models import BusinessProfile, OperatingExpense, Product
from apps.ledger.models import Account
from apps.onboarding.services import first_space as fs
from apps.onboarding.services.steps import completeness, get_state
from apps.personal.models import Commitment, EssentialEstimate, IncomeSource, SavingsGoal
from apps.workspaces.models import Workspace

pytestmark = pytest.mark.django_db
D = Decimal
START = reverse("asistente:first_space")


def step_url(key):
    return reverse("asistente:first_space_step", args=[key])


def answer(client, key, value=None, skip=False, **extra):
    data = {"saltar": "1"} if skip else {"valor": value, **extra}
    return client.post(step_url(key), data)


@pytest.fixture
def logged(client, user):
    client.force_login(user)
    return client


PERSONAL_FLOW = [
    ("uso", "persona"),
    ("moneda", "DOP"),
    ("frecuencia", "quincenal"),
    ("monto_ingreso", "25,000"),
    ("dia_cobro", "15,30"),
    ("dinero_hoy", "RD$ 12,500"),
    ("vivienda", "alquiler"),
    ("monto_vivienda", "18 mil"),
    ("dia_vivienda", "5"),
    ("comida", "12000"),
    ("transporte", None),  # saltado
    ("ahorro", "Fondo de emergencia"),
    ("monto_ahorro", "3,000"),
]


def walk(client, flow):
    for key, value in flow:
        response = (
            answer(client, key, skip=value is None) if value is None else answer(client, key, value)
        )
        assert response.status_code == 302, (key, response.content[:300])
    return response


# ---------------------------------------------------------------- recorrido


def test_primer_ingreso_abre_el_paso_a_paso(logged):
    response = logged.get(reverse("home"))
    assert response["Location"] == START
    page = logged.get(START, follow=True)
    html = page.content.decode()
    assert page.redirect_chain[-1][0] == step_url("uso")
    assert "¿Qué quieres organizar?" in html
    assert 'data-testid="paso">Paso 1 de' in html
    assert 'data-opcion="persona"' in html and 'data-opcion="ambos"' in html
    # Pantalla enfocada: sin barra lateral ni formularios de otros pasos.
    assert "Registrar movimiento" not in html


def test_el_indicador_se_ajusta_a_lo_elegido(logged):
    answer(logged, "uso", "persona")
    personal = fs.progress(logged.session[fs.SESSION_KEY], "moneda")
    answer(logged, "uso", "ambos")
    both = fs.progress(logged.session[fs.SESSION_KEY], "moneda")
    assert personal["number"] == both["number"] == 2
    assert both["total"] > personal["total"]
    assert [g["name"] for g in both["groups"]] == [
        "Tu espacio", "Tus ingresos", "Tus gastos", "Tu negocio", "Confirmar",
    ]  # fmt: skip
    html = logged.get(step_url("moneda")).content.decode()
    assert f"Te faltan {both['left']} pasos" in html


def test_pasos_condicionales(logged):
    walk(logged, PERSONAL_FLOW[:7])  # hasta «pago alquiler»
    assert fs.next_step(logged.session[fs.SESSION_KEY]) == "monto_vivienda"
    answer(logged, "vivienda", "no")
    answers = logged.session[fs.SESSION_KEY]
    assert fs.next_step(answers) == "comida" and "monto_vivienda" not in fs.path(answers)


def test_no_se_saltan_pasos_pendientes(logged):
    answer(logged, "uso", "persona")
    assert logged.get(step_url("comida"))["Location"] == step_url("moneda")
    assert logged.get(step_url("resumen"))["Location"] == step_url("moneda")
    assert logged.get(step_url("inventado"))["Location"] == step_url("moneda")


def test_errores_de_validacion(logged):
    answer(logged, "uso", "persona")
    response = answer(logged, "moneda", "EUR")
    assert response.status_code == 400 and "Elige una de las opciones." in response.content.decode()
    answer(logged, "moneda", "DOP")
    answer(logged, "frecuencia", "mensual")
    response = answer(logged, "monto_ingreso", "mucho")
    assert (
        response.status_code == 400
        and "Escribe un monto mayor que cero" in response.content.decode()
    )
    # El ingreso no se puede saltar.
    answer(logged, "monto_ingreso", skip=True)
    assert "monto_ingreso" not in logged.session[fs.SESSION_KEY]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("35,000", D("35000.00")), ("35.000", D("35000.00")), ("RD$ 1,250.50", D("1250.50")),
     ("35 mil", D("35000.00")), ("850", D("850.00")), ("0", None), ("abc", None)],
)  # fmt: skip
def test_montos(raw, expected):
    assert fs.parse_amount(raw) == expected


# ---------------------------------------------------------------- crear


def test_crea_el_espacio_personal_con_todo_lo_respondido(logged, user):
    walk(logged, PERSONAL_FLOW)
    summary = logged.get(step_url("resumen")).content.decode()
    assert "¡Listo! Revisa lo que me contaste" in summary
    assert "RD$25,000.00" in summary and "El 15 y el 30" in summary and "No gasto en eso" in summary
    assert not Workspace.objects.filter(owner=user).exists()  # nada se guarda antes de confirmar

    response = logged.post(reverse("asistente:first_space_create"))
    ws = Workspace.objects.get(owner=user)
    assert response["Location"] == reverse("espacio:dashboard", kwargs={"ws": ws.pk})
    assert ws.kind == "personal" and ws.currency == "DOP"
    income = IncomeSource.objects.for_workspace(ws).get()
    assert (income.net_amount, income.frequency, income.pay_days) == (
        D("25000"),
        "quincenal",
        [15, 30],
    )
    assert Account.objects.for_workspace(ws).get(name="Efectivo").opening_balance == D("12500")
    rent = Commitment.objects.for_workspace(ws).get()
    assert rent.due_day == 5
    assert (rent.name, rent.amount, rent.category.name) == (
        "Alquiler",
        D("18000"),
        "Alquiler o hipoteca",
    )
    assert EssentialEstimate.objects.for_workspace(ws).get().amount == D("12000")
    goal = SavingsGoal.objects.for_workspace(ws).get()
    assert (goal.purpose, goal.contribution_amount) == ("Fondo de emergencia", D("3000"))
    assert completeness(ws).minimum_ready
    assert get_state(ws).finished_at is not None
    assert fs.SESSION_KEY not in logged.session


def test_crea_el_negocio(logged, user):
    walk(logged, [
        ("uso", "negocio"), ("moneda", "USD"), ("nombre_negocio", "Dulces Ariel"),
        ("actividad", "Repostería"), ("modelo", "productos"), ("producto", "Bizcocho"),
        ("precio", "850"), ("costo", None), ("dinero_negocio", "20,000"),
        ("gastos_negocio", "15,000"),
    ])  # fmt: skip
    logged.post(reverse("asistente:first_space_create"))
    ws = Workspace.objects.get(owner=user)
    assert (ws.kind, ws.name, ws.currency) == ("business", "Dulces Ariel", "USD")
    assert BusinessProfile.objects.get(workspace=ws).activity == "Repostería"
    product = Product.objects.for_workspace(ws).get()
    assert (product.name, product.price, product.unit_cost) == ("Bizcocho", D("850"), D("0"))
    assert OperatingExpense.objects.for_workspace(ws).get().amount == D("15000")
    assert completeness(ws).minimum_ready


def test_ambos_crea_los_dos_espacios(logged, user):
    flow = [("uso", "ambos"), *PERSONAL_FLOW[1:], ("nombre_negocio", "Dulces Ariel"),
            ("actividad", "Repostería"), ("modelo", "servicios"), ("producto", "Clase"),
            ("precio", "1,500"), ("costo", "300"), ("dinero_negocio", None),
            ("gastos_negocio", None)]  # fmt: skip
    walk(logged, flow)
    logged.post(reverse("asistente:first_space_create"))
    assert set(Workspace.objects.filter(owner=user).values_list("kind", flat=True)) == {
        "personal",
        "business",
    }
    assert Product.objects.get(name="Clase").is_service


def test_cambiar_desde_el_resumen_vuelve_al_resumen(logged):
    walk(logged, PERSONAL_FLOW)
    response = logged.post(
        step_url("comida") + "?volver=resumen", {"valor": "9000", "volver": "resumen"}
    )
    assert response["Location"] == step_url("resumen")
    # Si el cambio abre un paso nuevo, primero lo pide y luego vuelve al resumen.
    answer(logged, "vivienda", "no", volver="resumen")
    response = answer(logged, "vivienda", "hipoteca", volver="resumen")
    assert response["Location"] == step_url("monto_vivienda") + "?volver=resumen"
    response = answer(logged, "monto_vivienda", "20000", volver="resumen")
    assert response["Location"] == step_url("dia_vivienda") + "?volver=resumen"
    response = answer(logged, "dia_vivienda", "1", volver="resumen")
    assert response["Location"] == step_url("resumen")


def test_quien_ya_tiene_espacio_personal_solo_ve_lo_que_falta(logged, personal_ws):
    html = logged.get(step_url("uso")).content.decode()
    assert 'data-opcion="negocio"' in html
    assert 'data-opcion="persona"' not in html and 'data-opcion="ambos"' not in html


def test_con_todos_los_espacios_va_al_selector(logged, personal_ws, business_ws):
    assert logged.get(START)["Location"] == reverse("workspaces:selector")


def test_empezar_de_nuevo(logged):
    answer(logged, "uso", "persona")
    logged.post(reverse("asistente:first_space_restart"))
    assert fs.SESSION_KEY not in logged.session


def test_anonimo_va_a_login(client):
    assert reverse("account_login") in client.get(START)["Location"]


# ---------------------------------------------------------------- crear otro espacio


def test_agregar_espacio_ofrece_tarjetas_o_chat(logged, personal_ws):
    dashboard = logged.get(reverse("espacio:dashboard", kwargs={"ws": personal_ws.pk}))
    assert reverse("asistente:new_space") in dashboard.content.decode()  # barra lateral
    html = logged.get(reverse("asistente:new_space")).content.decode()
    assert "¿Cómo prefieres crear tu nuevo espacio?" in html
    assert f'href="{START}" data-testid="modo-tarjetas"' in html
    assert f'href="{reverse("asistente:chat")}" data-testid="modo-chat"' in html
    # Las tarjetas solo ofrecen lo que aún puede crear.
    page = logged.get(step_url("uso")).content.decode()
    assert 'data-opcion="negocio"' in page and 'data-opcion="persona"' not in page


def test_agregar_espacio_retoma_un_paso_a_paso_a_medias(logged, personal_ws):
    answer(logged, "uso", "negocio")
    assert "Sigues donde lo dejaste" in logged.get(reverse("asistente:new_space")).content.decode()


def test_el_chat_ofrece_cambiar_a_tarjetas(logged, personal_ws):
    html = logged.get(reverse("asistente:chat")).content.decode()
    assert f'href="{START}" data-testid="a-tarjetas"' in html


def test_agregar_espacio_con_todo_creado(logged, personal_ws, business_ws):
    html = logged.get(reverse("asistente:new_space")).content.decode()
    assert "Ya tienes tus espacios" in html and 'data-testid="modo-tarjetas"' not in html


def test_negocio_creado_con_tarjetas_por_quien_ya_tiene_espacio_personal(logged, user, personal_ws):
    walk(logged, [
        ("uso", "negocio"), ("moneda", "DOP"), ("nombre_negocio", "Taller Luis"),
        ("actividad", "Mecánica"), ("modelo", "servicios"), ("producto", "Cambio de aceite"),
        ("precio", "1,800"), ("costo", "900"), ("dinero_negocio", None), ("gastos_negocio", None),
    ])  # fmt: skip
    response = logged.post(reverse("asistente:first_space_create"))
    negocio = Workspace.objects.get(owner=user, kind="business")
    assert response["Location"] == reverse("espacio:dashboard", kwargs={"ws": negocio.pk})
    assert Workspace.objects.filter(owner=user).count() == 2
