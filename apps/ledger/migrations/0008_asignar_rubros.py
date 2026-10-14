"""Asigna rubros a las categorías y gastos personales existentes y agrega «Turismo nacional»."""

import uuid

from django.db import migrations

RUBROS = {
    "Alimentación": "alimentacion",
    "Restaurantes y delivery": "alimentacion",
    "Educación": "educacion",
    "Salud y farmacia": "salud",
    "Seguros": "salud",
    "Alquiler o hipoteca": "vivienda",
    "Electricidad": "vivienda",
    "Agua": "vivienda",
    "Internet y teléfono": "vivienda",
    "Aseo y hogar": "vivienda",
    "Ropa": "vestimenta",
    "Turismo nacional": "turismo_nacional",
}
SIN_RUBRO = {"ingreso", "ahorro"}


def forwards(apps, schema_editor):
    Workspace = apps.get_model("workspaces", "Workspace")
    Category = apps.get_model("ledger", "Category")
    Transaction = apps.get_model("ledger", "Transaction")
    personal = Workspace.objects.filter(kind="personal")
    for workspace in personal:
        if not Category.objects.filter(workspace=workspace, name="Turismo nacional").exists():
            Category.objects.create(
                id=uuid.uuid4(),
                workspace=workspace,
                name="Turismo nacional",
                group="discrecional",
                is_system=True,
                rubro="turismo_nacional",
            )
    for category in Category.objects.filter(workspace__kind="personal", rubro=""):
        if category.group in SIN_RUBRO:
            continue
        category.rubro = RUBROS.get(category.name, "otro")
        category.save(update_fields=["rubro"])
    gastos = Transaction.objects.filter(workspace__kind="personal", kind="gasto", rubro="")
    for tx in gastos.select_related("category"):
        tx.rubro = (tx.category.rubro if tx.category_id else "") or "otro"
        tx.save(update_fields=["rubro"])


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0007_rubros_y_factura"),
        ("workspaces", "0004_transferencias_con_tasa"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
