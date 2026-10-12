from apps.personal.services.budget_engine import build_personal_plan
from apps.personal.services.serialize import serialize_plan
from apps.personal.tests.builders import D, caso_50000, mensual


def computed_viable():
    return serialize_plan(build_personal_plan(caso_50000()), include_refs=False)


def computed_no_viable():
    return serialize_plan(
        build_personal_plan(caso_50000(incomes=(mensual("40000"),))), include_refs=False
    )


def computed_ajustado(**kw):
    return serialize_plan(build_personal_plan(caso_50000(**kw)), include_refs=False)


__all__ = ["D", "computed_ajustado", "computed_no_viable", "computed_viable"]
