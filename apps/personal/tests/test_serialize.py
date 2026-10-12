from apps.personal.services.budget_engine import build_personal_plan
from apps.personal.services.serialize import serialize_plan

from .builders import caso_50000, mensual


def test_serializacion_del_plan():
    data = serialize_plan(build_personal_plan(caso_50000(incomes=(mensual("40000"),))))
    assert data["estado"] == "no_viable"
    assert data["ingreso_total"] == "40000.00"
    assert data["faltante_total"] == "2000.00"
    assert data["faltantes_por_fecha"][0] == {
        "fecha": "2026-10-27",
        "monto": "64.52",
        "conceptos": ["Gastos del día a día"],
    }
    assert data["periodo"] == {"inicio": "2026-10-01", "fin": "2026-10-31", "dias": 31}
    assert data["lineas"][0]["ref"] == "alquiler"
    bajar = next(a for a in data["alternativas"] if a["codigo"] == "bajar_ahorro")
    assert bajar["cambios"][0]["concepto"] == "Fondo de emergencia"


def test_sin_referencias_para_la_ia():
    data = serialize_plan(build_personal_plan(caso_50000()), include_refs=False)
    assert "ref" not in data["lineas"][0]
    assert "categoria_ref" not in data["lineas"][0]
    assert data["saldo_mas_bajo"] == {"fecha": "2026-10-31", "monto": "3000.00"}


def test_ida_y_vuelta_de_las_entradas():
    from apps.personal.services.serialize import inputs_from_dict, inputs_to_dict
    from apps.personal.services.types import DebtInput

    from .builders import D, ahorro

    deuda = DebtInput("p", "Préstamo", D("4000"), D("9000"), 10, interest_rate=D("18.5"))
    inputs = caso_50000(debts=(deuda,), savings=(ahorro(target_amount=D("90000")),))
    again = inputs_from_dict(inputs_to_dict(inputs))
    assert again == inputs
    assert build_personal_plan(again).totals_by_kind == build_personal_plan(inputs).totals_by_kind


def test_quitar_referencias():
    from apps.personal.services.serialize import strip_refs

    data = strip_refs(serialize_plan(build_personal_plan(caso_50000(incomes=(mensual("40000"),)))))
    assert "ref" not in str(data.keys())
    assert all("ref" not in c for a in data["alternativas"] for c in a["cambios"])
