"""Primer espacio con Sophia: un paso por pantalla, con tarjetas o una caja de texto
(ver `services/first_space.py`)."""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.money import fmt

from .services import first_space as fs
from .services import savings_review

SYMBOLS = {"DOP": "RD$", "USD": "US$"}


def _answers(request: HttpRequest) -> dict[str, Any]:
    return dict(request.session.get(fs.SESSION_KEY, {}))


def _go(step: str, back_to_summary: bool = False) -> HttpResponse:
    url = reverse("asistente:first_space_step", args=[step])
    return redirect(url + ("?volver=resumen" if back_to_summary and step != "resumen" else ""))


@login_required
@require_http_methods(["GET", "POST"])
def wizard(request: HttpRequest, step: str | None = None) -> HttpResponse:
    user = request.user
    if not fs.usage_options(user):  # ya tiene todos los espacios que se pueden crear
        return redirect("workspaces:selector")
    answers = _answers(request)
    following = fs.next_step(answers)
    if step is None or step not in fs.path(answers):
        return _go(following)
    if step != "resumen" and step not in answers and step != following:
        return _go(following)  # no se salta pasos pendientes
    if step == "resumen":
        return _summary(request, answers, following)

    current = fs.STEPS[step]
    back_to_summary = request.GET.get("volver") == "resumen" or "volver" in request.POST
    error = None
    if request.method == "POST":
        if "saltar" in request.POST and fs.skip_label_for(current, answers):
            value: Any = ""
        elif "variable" in request.POST and current.kind == fs.FIXED:
            value = fs.VARIABLE  # cambia cada mes: no se llena ni se anota solo
        else:
            value, error = fs.clean_answer(
                current,
                request.POST.get("valor", ""),
                answers,
                user,
                request.POST,  # type: ignore[arg-type]
            )
        if error is None:
            fs.save_answer(answers, step, value)
            request.session[fs.SESSION_KEY] = answers
            following = fs.next_step(answers)
            return _go("resumen" if back_to_summary and following == "resumen" else following,
                       back_to_summary)  # fmt: skip

    previous = fs.previous_step(answers, step)
    context: dict[str, Any] = {
        "step": current,
        "question": fs.question_for(current, answers),
        "skip_label": fs.skip_label_for(current, answers),
        "variable_label": fs.VARIABLE_LABEL,
        "options": fs.options_for(current, answers, user),  # type: ignore[arg-type]
        "columns": fs.columns_for(current, answers),
        "progress": fs.progress(answers, step),
        "previous": reverse("asistente:first_space_step", args=[previous]) if previous else None,
        "value": _posted(request, current) if error else answers.get(step),
        "error": error,
        "symbol": SYMBOLS.get(answers.get("moneda") or "DOP", "RD$"),
        "back_to_summary": back_to_summary,
        "days": range(1, 32),
    }
    if current.kind == fs.OTHERS:
        saved = context["value"] if isinstance(context["value"], list) else []
        context["other_rows"] = [
            {"i": i, **(saved[i - 1] if i <= len(saved) else {})}
            for i in range(1, fs.MAX_OTHERS + 1)
        ]
    if step == "monto_ahorro":
        context["suggestion"] = savings_review.suggestion(answers)
        # Aquí sin IA: el ejemplo sale de las mismas cifras, sin gastar una consulta.
        context.update(_method_context(savings_review.build(answers, ignore_wanted=True)))
    if current.kind == fs.REVIEW:
        context.update(_review_context(request, answers))
    return render(request, "onboarding/first_space.html", context, status=400 if error else 200)


def _posted(request: HttpRequest, step: fs.Step) -> Any:
    """Lo enviado, para volver a mostrarlo junto al error."""
    if step.kind == fs.FIXED:
        return {"monto": request.POST.get("valor", ""), "dia": request.POST.get("dia", "")}
    if step.kind == fs.OTHERS:
        return [
            {
                "nombre": request.POST.get(f"nombre_{i}", ""),
                "monto": request.POST.get(f"valor_{i}", ""),
                "dia": request.POST.get(f"dia_{i}", ""),
            }
            for i in range(1, fs.MAX_OTHERS + 1)
        ]
    return request.POST.get("valor")


def _review_context(request: HttpRequest, answers: dict[str, Any]) -> dict[str, Any]:
    review = savings_review.build(answers)
    explanation, from_ai = savings_review.explain(review, request.user, request.session)  # type: ignore[arg-type]
    currency = review.currency
    return {
        "review": review,
        "review_rows": review.rule_503020(),
        "review_figures": [
            ("Ingreso del mes", fmt(review.income, currency)),
            ("Gastos fijos", fmt(review.fixed, currency)),
            ("Gastos del día a día", fmt(review.essentials, currency)),
            ("Te queda libre", fmt(review.free, currency)),
        ],
        "explanation": explanation,
        "from_ai": from_ai,
        "recommended": explanation.metodo_recomendado,
        **_method_context(review, explanation.explicacion_metodo if from_ai else ""),
    }


def _method_context(review: savings_review.Review, ai_text: str = "") -> dict[str, Any]:
    """«Saber más del método 50/30/20»: Sophia lo explica con el ingreso de la persona."""
    method = savings_review.method_example(review)
    return {"method": method, "method_text": ai_text or method["texto"],
            "method_from_ai": bool(ai_text)}  # fmt: skip


def _summary(request: HttpRequest, answers: dict[str, Any], following: str) -> HttpResponse:
    if following != "resumen":
        return _go(following)
    currency = answers.get("moneda") or "DOP"
    rows = [
        {
            "key": key,
            "group": fs.STEPS[key].group,
            "question": fs.LABELS[key],
            "answer": fs.display(answers, key, currency, request.user),  # type: ignore[arg-type]
        }
        for key in fs.path(answers)
        if key != "resumen"
    ]
    return render(
        request,
        "onboarding/first_space.html",
        {
            "summary": rows,
            "progress": fs.progress(answers, "resumen"),
            "previous": reverse(
                "asistente:first_space_step", args=[fs.previous_step(answers, "resumen")]
            ),
        },
    )


@login_required
@require_POST
def create(request: HttpRequest) -> HttpResponse:
    answers = _answers(request)
    try:
        created = fs.create(request.user, answers)  # type: ignore[arg-type]
    except fs.CreationError as exc:
        messages.error(request, f"No pude crear tu espacio: {exc}")
        return _go(exc.step, back_to_summary=True)
    request.session.pop(fs.SESSION_KEY, None)
    request.session.pop(savings_review.SESSION_KEY, None)
    names = " y ".join(f"«{w.name}»" for w in created)
    messages.success(request, f"¡Listo! Sophia preparó {names}. Este es tu panel.")
    return redirect("espacio:dashboard", ws=created[0].pk)


@login_required
@require_http_methods(["GET"])
def new_space(request: HttpRequest) -> HttpResponse:
    """Crear otro espacio: elegir entre el paso a paso con tarjetas y el chat con Sophia."""
    return render(
        request,
        "onboarding/new_space.html",
        {
            "can_create": bool(fs.usage_options(request.user)),  # type: ignore[arg-type]
            "in_progress": bool(request.session.get(fs.SESSION_KEY)),
        },
    )


@login_required
@require_POST
def restart(request: HttpRequest) -> HttpResponse:
    request.session.pop(fs.SESSION_KEY, None)
    request.session.pop(savings_review.SESSION_KEY, None)
    return redirect("asistente:first_space")
