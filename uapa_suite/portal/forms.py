from django import forms


class BootstrapMixin:
    """Añade las clases de Bootstrap a todos los widgets del formulario."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            w = campo.widget
            clase = "form-select" if isinstance(w, forms.Select) else "form-control"
            if isinstance(w, forms.CheckboxInput):
                clase = "form-check-input"
            w.attrs["class"] = f"{w.attrs.get('class', '')} {clase}".strip()
