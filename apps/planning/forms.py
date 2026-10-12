from decimal import Decimal

from django import forms

from apps.planning.models import PlanVersion


class EditPlanForm(forms.Form):
    """Formulario construido a partir del snapshot de la propuesta."""

    alternativa = forms.ChoiceField(label="Aplicar una alternativa", required=False)
    ocio_deseado = forms.DecimalField(
        label="Ocio deseado", required=False, min_value=0, max_digits=14, decimal_places=2
    )
    reserva_pct = forms.DecimalField(
        label="Reserva para variaciones (% de esenciales)",
        min_value=0,
        max_value=50,
        max_digits=5,
        decimal_places=2,
    )

    def __init__(self, plan: PlanVersion, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        snapshot = plan.inputs_snapshot
        self.essential_refs: list[str] = []
        self.savings_refs: list[str] = []
        self.fields["alternativa"].choices = [("", "Ninguna")] + [
            (a["codigo"], a["nombre"]) for a in plan.computed.get("alternativas", [])
        ]
        self.fields["ocio_deseado"].initial = snapshot.get("ocio_deseado")
        self.fields["reserva_pct"].initial = Decimal(snapshot["reserva_pct"]) * 100
        for item in snapshot["esenciales"]:
            name = f"esencial_{item['ref']}"
            self.essential_refs.append(item["ref"])
            self.fields[name] = forms.DecimalField(
                label=item["nombre"],
                min_value=0,
                max_digits=14,
                decimal_places=2,
                initial=item["monto"],
            )
        for goal in snapshot["ahorro"]:
            name = f"ahorro_{goal['ref']}"
            self.savings_refs.append(goal["ref"])
            self.fields[name] = forms.DecimalField(
                label=f"Aporte a {goal['proposito']} ({goal['frecuencia']})",
                min_value=0,
                max_digits=14,
                decimal_places=2,
                initial=goal["aporte"],
            )

    def to_edits(self) -> dict:
        data = self.cleaned_data
        edits: dict = {
            "ocio_deseado": None if data["ocio_deseado"] is None else str(data["ocio_deseado"]),
            "reserva_pct": str(data["reserva_pct"] / 100),
            "esenciales": {r: str(data[f"esencial_{r}"]) for r in self.essential_refs},
            "ahorro": {r: str(data[f"ahorro_{r}"]) for r in self.savings_refs},
        }
        if data.get("alternativa"):
            edits["alternativa"] = data["alternativa"]
        return edits
