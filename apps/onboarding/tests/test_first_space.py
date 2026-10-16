from decimal import Decimal

import pytest
from django.urls import reverse

from apps.ai.providers import FakeProvider
from apps.business.models import BusinessProfile, OperatingExpense, Product
from apps.ledger.models import Account
from apps.onboarding.services import first_space as fs
from apps.onboarding.services import savings_review
from apps.onboarding.services.steps import completeness, get_state
from apps.personal.models import (
    Commitment,
    EssentialEstimate,
    IncomeSource,
    PersonalProfile,
    SavingsGoal,
)
from apps.workspaces.models import Workspace

pytestmark = pytest.mark.django_db
D = Decimal
START = reverse("asistente:first_space")


def step_url(key):
    return reverse("asistente:first_space_step", args=[key])


def answer(client, key, value=None, skip=False, **extra):
    if skip:
        data = {"saltar": "1"}
    elif value == VARIA:
        data = {"variable": "1"}
    elif isinstance(value, dict):
        data = value
    else:
        data = {"valor": value}
    return client.post(step_url(key), {**data, **extra})


@pytest.fixture
def logged(client, user):
    client.force_login(user)
    return client


VARIA = object()  # «Varía cada mes» en un gasto fijo
PERSONAL_FLOW = [
    ("uso", "persona"),
    ("moneda", "DOP"),
    ("frecuencia", "quincenal"),
    ("quincenas", "igual"),
    ("monto_ingreso", "25,000"),
    ("dia_cobro", "15,30"),
    ("cuenta_cobro", "efectivo"),
    ("efectivo_hoy", "RD$ 12,500"),
    ("banco_hoy", None),  # saltado: no tiene cuenta bancaria
    ("vivienda", "alquiler"),
    ("monto_vivienda", "18 mil"),
    ("dia_vivienda", "5"),
    ("luz", VARIA),
    ("agua", {"valor": "500", "dia": "10"}),
    ("internet", {"valor": "2,200", "dia": "20"}),
    ("seguros", None),
    ("deudas", None),
    ("otros_fijos", None),
    ("comida", "12000"),
    ("aseo", None),
    ("transporte", None),  # saltado
    ("automatico", "no"),
    ("ahorro", "Fondo de emergencia"),
    ("monto_ahorro", "3,000"),
    ("revision", "mantener"),
]


def flow_until(key):
    return PERSONAL_FLOW[: [k for k, _ in PERSONAL_FLOW].index(key)]


def walk(client, flow):
    for key, value in flow:
        response = answer(client, key, value, skip=value is None)
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
        "Tu espacio", "Tus ingresos", "Tus gastos", "Tu ahorro", "Tu negocio", "Confirmar",
    ]  # fmt: skip
    html = logged.get(step_url("moneda")).content.decode()
    assert f"Te faltan {both['left']} pasos" in html


def test_pasos_condicionales(logged):
    walk(logged, flow_until("monto_vivienda"))  # hasta «pago alquiler»
    assert fs.next_step(logged.session[fs.SESSION_KEY]) == "monto_vivienda"
    answer(logged, "vivienda", "no")
    answers = logged.session[fs.SESSION_KEY]
    assert fs.next_step(answers) == "luz" and "monto_vivienda" not in fs.path(answers)


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
    assert "Varía cada mes" in summary and "RD$2,200.00 · día 20" in summary
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
    assert not Account.objects.for_workspace(ws).filter(type="banco").exists()
    commitments = {
        c.name: (c.amount, c.due_day, c.category.name) for c in Commitment.objects.for_workspace(ws)
    }
    # La luz «varía cada mes»: no se guarda como pago fijo.
    assert commitments == {
        "Alquiler": (D("18000"), 5, "Alquiler o hipoteca"),
        "Agua": (D("500"), 10, "Agua"),
        "Internet y teléfono": (D("2200"), 20, "Internet y teléfono"),
    }
    assert EssentialEstimate.objects.for_workspace(ws).get().amount == D("12000")
    goal = SavingsGoal.objects.for_workspace(ws).get()
    assert (goal.purpose, goal.contribution_amount) == ("Fondo de emergencia", D("3000"))
    assert not PersonalProfile.objects.filter(workspace=ws).exists()  # sin registro automático
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
    response = answer(logged, "automatico", "si", volver="resumen")
    assert response["Location"] == step_url("resumen")
    # Si cambian los gastos, Sophia vuelve a revisar el ahorro antes del resumen.
    response = logged.post(
        step_url("comida") + "?volver=resumen", {"valor": "9000", "volver": "resumen"}
    )
    assert response["Location"] == step_url("revision") + "?volver=resumen"
    response = answer(logged, "revision", "mantener", volver="resumen")
    assert response["Location"] == step_url("resumen")
    # Si el cambio abre un paso nuevo, primero lo pide y luego vuelve al resumen.
    answer(logged, "vivienda", "no", volver="resumen")
    response = answer(logged, "vivienda", "hipoteca", volver="resumen")
    assert response["Location"] == step_url("monto_vivienda") + "?volver=resumen"
    response = answer(logged, "monto_vivienda", "20000", volver="resumen")
    assert response["Location"] == step_url("dia_vivienda") + "?volver=resumen"
    response = answer(logged, "dia_vivienda", "1", volver="resumen")
    assert response["Location"] == step_url("revision") + "?volver=resumen"
    response = answer(logged, "revision", "mantener", volver="resumen")
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


def flow_from(key):
    return PERSONAL_FLOW[[k for k, _ in PERSONAL_FLOW].index(key) :]


# ---------------------------------------------------------------- ingresos y cuentas


def test_quincenas_con_montos_distintos_crean_dos_cobros(logged, user):
    walk(logged, flow_until("quincenas"))
    html = logged.get(step_url("quincenas")).content.decode()
    assert "¿Recibes lo mismo en cada quincena?" in html
    answer(logged, "quincenas", "distinto")
    html = logged.get(step_url("monto_ingreso")).content.decode()
    assert "¿Cuánto recibes en la primera quincena?" in html
    walk(logged, [("monto_ingreso", "20,000"), ("monto_ingreso_2", "26,500")])
    walk(logged, flow_from("dia_cobro"))
    logged.post(reverse("asistente:first_space_create"))
    ws = Workspace.objects.get(owner=user)
    incomes = {
        i.name: (i.net_amount, i.frequency, i.pay_days)
        for i in IncomeSource.objects.for_workspace(ws)
    }
    assert incomes == {
        "Cobro del 15": (D("20000"), "mensual", [15]),
        "Cobro del 30": (D("26500"), "mensual", [30]),
    }


def test_quien_cambia_a_mensual_ya_no_ve_las_quincenas(logged):
    walk(logged, flow_until("quincenas"))
    answer(logged, "quincenas", "distinto")
    answer(logged, "frecuencia", "mensual")
    answers = logged.session[fs.SESSION_KEY]
    assert "quincenas" not in answers and "monto_ingreso_2" not in fs.path(answers)


def test_efectivo_y_cuenta_bancaria(logged, user):
    flow = dict(PERSONAL_FLOW)
    flow.update({"cuenta_cobro": "banco", "efectivo_hoy": "1,500", "banco_hoy": "40,000",
                 "automatico": "si"})  # fmt: skip
    walk(logged, list(flow.items()))
    logged.post(reverse("asistente:first_space_create"))
    ws = Workspace.objects.get(owner=user)
    accounts = {a.name: (a.type, a.opening_balance) for a in Account.objects.for_workspace(ws)}
    assert accounts == {
        "Efectivo": ("efectivo", D("1500")),
        "Cuenta bancaria": ("banco", D("40000")),
    }
    profile = PersonalProfile.objects.get(workspace=ws)
    assert profile.auto_record and profile.auto_account.name == "Cuenta bancaria"
    assert profile.auto_since is not None


def test_quien_cobra_en_el_banco_puede_no_decir_su_saldo(logged, user):
    walk(logged, flow_until("cuenta_cobro"))
    answer(logged, "cuenta_cobro", "banco")
    answer(logged, "efectivo_hoy", skip=True)
    assert "Prefiero no decirlo" in logged.get(step_url("banco_hoy")).content.decode()
    answer(logged, "banco_hoy", skip=True)
    walk(logged, flow_from("vivienda"))
    logged.post(reverse("asistente:first_space_create"))
    ws = Workspace.objects.get(owner=user)
    assert Account.objects.for_workspace(ws).get(type="banco").opening_balance == 0


# ---------------------------------------------------------------- gastos fijos


def test_gasto_fijo_pide_monto_y_dia(logged):
    walk(logged, flow_until("luz"))
    html = logged.get(step_url("luz")).content.decode()
    assert 'name="dia"' in html and "Varía cada mes" in html and "No pago luz" in html
    response = answer(logged, "luz", {"valor": "2,500"})
    assert response.status_code == 400
    assert "Elige el día del mes en que lo pagas." in response.content.decode()
    assert 'value="2,500"' in response.content.decode()  # no se pierde lo escrito
    assert answer(logged, "luz", {"valor": "2,500", "dia": "8"}).status_code == 302
    assert logged.session[fs.SESSION_KEY]["luz"] == {"monto": "2500.00", "dia": 8}


def test_otros_gastos_fijos(logged, user):
    walk(logged, flow_until("otros_fijos"))
    response = answer(logged, "otros_fijos", {"nombre_1": "Colegio", "valor_1": "6,000"})
    assert response.status_code == 400 and "elige el día" in response.content.decode()
    response = answer(logged, "otros_fijos", {})
    assert "Escribe al menos un gasto" in response.content.decode()
    rows = {"nombre_1": "Colegio", "valor_1": "6,000", "dia_1": "1",
            "nombre_3": "Gimnasio", "valor_3": "1,200", "dia_3": "15"}  # fmt: skip
    assert answer(logged, "otros_fijos", rows).status_code == 302
    walk(logged, flow_from("comida"))
    assert "Colegio: RD$6,000.00 · día 1" in logged.get(step_url("resumen")).content.decode()
    logged.post(reverse("asistente:first_space_create"))
    ws = Workspace.objects.get(owner=user)
    colegio = Commitment.objects.for_workspace(ws).get(name="Colegio")
    assert (colegio.amount, colegio.due_day, colegio.category.name) == (D("6000"), 1, "Educación")
    gym = Commitment.objects.for_workspace(ws).get(name="Gimnasio")
    assert gym.category.name == "Otros gastos"  # sin categoría parecida


def test_volver_al_paso_anterior_desde_arriba(logged):
    walk(logged, flow_until("agua"))
    html = logged.get(step_url("agua")).content.decode()
    assert f'href="{step_url("luz")}" data-testid="paso-anterior"' in html


# ---------------------------------------------------------------- ahorro


def test_ahorro_ofrece_aumentar_mis_ahorros(logged):
    walk(logged, flow_until("ahorro"))
    assert 'data-opcion="Aumentar mis ahorros"' in logged.get(step_url("ahorro")).content.decode()


def test_sugiere_un_ahorro_con_los_gastos_anotados(logged):
    walk(logged, flow_until("monto_ahorro"))
    # Ingreso RD$50,000; necesidades RD$32,700: el 20 % (RD$10,000) cabe.
    html = logged.get(step_url("monto_ahorro")).content.decode()
    assert 'data-testid="sugerencia-ahorro"' in html
    assert "Método 50/30/20: RD$10,000.00 al mes" in html


def test_revision_explica_el_50_30_20_y_recomienda(logged):
    walk(logged, flow_until("revision"))
    html = logged.get(step_url("revision")).content.decode()
    assert "El método 50/30/20 con tu ingreso" in html
    assert "Sugerido RD$25,000.00 · tú RD$32,700.00 (65 %)" in html  # necesidades
    assert "Calculado por Crecenta" in html  # sin consentimiento de IA: reglas
    assert 'data-opcion="mantener"' in html and 'data-opcion="50_30_20"' in html
    # Ahorra menos del 20 % y le alcanza: se recomienda el 50/30/20.
    badge = html.index('data-testid="recomendada"')
    assert html.index('data-opcion="50_30_20"') < badge < html.index('data-opcion="pagate_primero"')
    answer(logged, "revision", "50_30_20")
    answers = logged.session[fs.SESSION_KEY]
    assert answers["monto_ahorro"] == "10000"
    assert answers["revision"]["texto"] == "Método 50/30/20: RD$10,000.00 al mes"


def test_revision_cuando_no_alcanza(logged):
    flow = dict(PERSONAL_FLOW)
    flow["monto_ahorro"] = "30,000"
    walk(logged, list(flow.items())[:-1])
    html = logged.get(step_url("revision")).content.decode()
    assert "no te alcanza" in html
    review = savings_review.build(logged.session[fs.SESSION_KEY])
    assert review.status == "no_alcanza" and review.recommended == "50_30_20"
    answer(logged, "revision", "ahora_no")
    answers = logged.session[fs.SESSION_KEY]
    assert answers["ahorro"] == "no" and "monto_ahorro" not in answers


def test_revision_sin_meta_puede_empezar_a_ahorrar(logged):
    flow = [(k, v) for k, v in PERSONAL_FLOW if k not in ("monto_ahorro", "revision")]
    flow[[k for k, _ in flow].index("ahorro")] = ("ahorro", "no")
    walk(logged, flow)
    answer(logged, "revision", "pagate_primero")
    answers = logged.session[fs.SESSION_KEY]
    assert (answers["ahorro"], answers["monto_ahorro"]) == ("Fondo de emergencia", "5000")


def test_revision_con_ia(logged, user):
    user.ai_consent = True
    user.save()
    walk(logged, flow_until("revision"))
    FakeProvider.queue(
        {"mensaje": "Tu plan cabe.", "motivos": ["Te sobra"], "metodo_recomendado": "inventado"},
        {"mensaje": "Tu plan cabe y puedes ahorrar más.", "motivos": ["Te quedan RD$17,300.00"],
         "metodo_recomendado": "pagate_primero",
         "explicacion_metodo": "Imagina tus RD$50,000.00 en tres sobres."},
    )  # fmt: skip
    html = logged.get(step_url("revision")).content.decode()
    assert "Tu plan cabe y puedes ahorrar más." in html and "Explicación de Sophia con IA" in html
    assert "Imagina tus RD$50,000.00 en tres sobres." in html  # «Saber más», escrito por la IA
    badge = html.index('data-testid="recomendada"')
    assert html.index('data-opcion="pagate_primero"') < badge
    # La primera respuesta recomendaba una opción que no existe: se le pidió corregir.
    assert len(FakeProvider.calls) == 2
    logged.get(step_url("revision"))  # mismas cifras: no vuelve a consultar
    assert len(FakeProvider.calls) == 2


def test_saber_mas_del_503020_con_el_ingreso_del_usuario(logged):
    walk(logged, flow_until("monto_ahorro"))
    html = logged.get(step_url("monto_ahorro")).content.decode()
    assert "Saber más del método 50/30/20" in html
    # Cobra RD$25,000 cada quincena: el ejemplo usa su ingreso de RD$50,000 al mes.
    assert (
        "Con tu ingreso de RD$50,000.00 al mes serían RD$25,000.00 para necesidades, "
        "RD$15,000.00 para gustos y RD$10,000.00 para ahorro." in html
    )
    assert "cada vez que te llegue el dinero aparta RD$5,000.00 para el ahorro" in html
    assert "pasan del 50 % por RD$7,700.00" in html  # necesidades: RD$32,700
    assert "RD$5,000.00 cada quincena" in html and "Hoy: RD$32,700.00 (65 %)" in html
    walk(logged, [("monto_ahorro", "3,000")])
    html = logged.get(step_url("revision")).content.decode()
    assert 'data-testid="saber-mas-503020"' in html and "Ejemplo calculado por Crecenta" in html


def test_ejemplo_503020_dentro_del_50():
    review = savings_review.build(
        {"frecuencia": "mensual", "monto_ingreso": "40000", "comida": "10000"}
    )
    example = savings_review.method_example(review)
    assert example["cuando"] == "" and all(row["por_cobro"] == "" for row in example["filas"])
    assert "están dentro del 50 %" in example["texto"]
    assert [row["monto"] for row in example["filas"]] == [
        "RD$20,000.00",
        "RD$12,000.00",
        "RD$8,000.00",
    ]


def test_cifras_de_la_revision():
    answers = {"frecuencia": "semanal", "monto_ingreso": "6000", "moneda": "USD",
               "luz": {"monto": "100", "dia": 3}, "otros_fijos": [{"monto": "50", "dia": 1}],
               "seguros": "variable", "comida": "400", "ahorro": "no"}  # fmt: skip
    review = savings_review.build(answers)
    assert review.income == D("26000.00") and review.needs == D("550")
    assert review.choice("50_30_20").amount == D("5200")  # de 10 en 10 en dólares
    deficit = savings_review.build(
        {"frecuencia": "mensual", "monto_ingreso": "1000", "comida": "1200"}
    )
    assert deficit.status == "deficit" and deficit.recommended == "ahora_no"
    explanation = savings_review.explain_by_rules(deficit)
    assert explanation.metodo_recomendado == "ahora_no" and "no te queda" in explanation.mensaje
