"""CentIA en «Registrar movimiento»: la persona cuenta el movimiento en un chat y CentIA arma el
borrador, pregunta lo que falta y lo deja listo para guardar.

La IA solo propone lo que entendió de cada mensaje (`MovementTurn`); el servidor empareja cuenta y
categoría con las reales del espacio, decide qué falta y solo guarda cuando la persona pulsa
«Guardar» (con la misma validación que el formulario). Sin IA —sin consentimiento, límite o
falla— el mensaje se interpreta con reglas simples.

El estado de la conversación es un dict serializable que la vista guarda en la sesión.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from django.urls import reverse

from apps.accounts.models import User
from apps.ai.schemas import MovementTurn
from apps.ai.services.client import run_structured
from apps.alerts.services.evaluate import purchase_warnings
from apps.core.money import fmt
from apps.ledger.choices import CategoryGroup, TxKind
from apps.ledger.forms import BUSINESS_QUICK_KINDS, QUICK_KINDS, QuickEntryForm
from apps.ledger.models import Account, Category
from apps.ledger.services.categories import SYNONYMS, match_account, match_category, normalize
from apps.workspaces.models import Workspace

NAME = "CentIA"
MAX_TURNS = 30
MAX_TEXT = 500
HISTORY = 6
MAX_OPTIONS = 6
TRANSFER_KINDS = {TxKind.TRANSFERENCIA_INTERNA, TxKind.RETIRO_EFECTIVO}

QUESTIONS = {
    "tipo": "¿Fue un gasto, un ingreso o la cuota de una deuda?",
    "monto": "¿De cuánto fue?",
    "cuenta": "¿Con qué cuenta fue?",
    "categoria": "¿En qué categoría lo pongo?",
}
NO_CATEGORY = "Sin categoría"
_SKIP = re.compile(r"\b(sin categoria|ninguna|ninguno|no se|omitir|da igual|no aplica)\b")


# ---------------------------------------------------------------- estado


def new_state(workspace: Workspace, user: User) -> dict[str, Any]:
    example = (
        "«pagué 4,500 al suplidor con la cuenta del banco»"
        if workspace.is_business
        else "«gasté 350 en el colmado ayer»"
    )
    return {
        "draft": {},
        "turns": 0,
        "messages": [
            {
                "rol": "centia",
                "texto": f"Soy {NAME}. Cuéntame el movimiento con tus palabras, por ejemplo "
                f"{example}, y yo lo preparo para que solo tengas que confirmarlo.",
                "enlaces": [],
            }
        ],
    }


def _say(state: dict[str, Any], text: str, links: list[dict[str, str]] | None = None) -> None:
    state["messages"].append({"rol": "centia", "texto": text, "enlaces": links or []})


def kinds(workspace: Workspace) -> dict[str, str]:
    return dict(BUSINESS_QUICK_KINDS if workspace.is_business else QUICK_KINDS)


def _accounts(workspace: Workspace) -> list[Account]:
    return list(Account.objects.for_workspace(workspace).filter(is_archived=False))


def _categories(workspace: Workspace, kind: str | None) -> list[Category]:
    items = Category.objects.for_workspace(workspace).filter(is_archived=False)
    if kind == TxKind.INGRESO:
        items = items.filter(group=CategoryGroup.INGRESO)
    elif kind:
        items = items.exclude(group=CategoryGroup.INGRESO)
    return list(items.order_by("group", "name"))


def missing(workspace: Workspace, draft: dict[str, Any]) -> list[str]:
    pending = []
    if not draft.get("kind"):
        pending.append("tipo")
    if not draft.get("amount"):
        pending.append("monto")
    if not draft.get("account_id"):
        pending.append("cuenta")
    if not draft.get("category_id") and not draft.get("category_skipped"):
        pending.append("categoria")
    return pending


def quick_replies(workspace: Workspace, state: dict[str, Any]) -> list[str]:
    pending = missing(workspace, state["draft"])
    if not pending:
        return []
    if pending[0] == "tipo":
        return list(kinds(workspace).values())
    if pending[0] == "cuenta":
        return [a.name for a in _accounts(workspace)[:MAX_OPTIONS]]
    if pending[0] == "categoria":
        names = [c.name for c in _categories(workspace, state["draft"].get("kind"))]
        return [*names[:MAX_OPTIONS], NO_CATEGORY]
    return []


def proposal(workspace: Workspace, state: dict[str, Any]) -> dict[str, Any] | None:
    """Movimiento listo para confirmar (o None si aún falta algo)."""
    draft = state["draft"]
    if missing(workspace, draft):
        return None
    account = Account.objects.for_workspace(workspace).filter(pk=draft["account_id"]).first()
    category = (
        Category.objects.for_workspace(workspace).filter(pk=draft["category_id"]).first()
        if draft.get("category_id")
        else None
    )
    if account is None:
        return None
    amount = Decimal(draft["amount"])
    warnings = (
        purchase_warnings(workspace, amount, category) if draft["kind"] != TxKind.INGRESO else []
    )
    return {
        "tipo": kinds(workspace).get(draft["kind"], draft["kind"]),
        "kind": draft["kind"],
        "monto": amount,
        "fecha": date.fromisoformat(draft["date"]),
        "cuenta": account,
        "categoria": category,
        "nota": draft.get("description", ""),
        "avisos": warnings,
    }


def form_initial(state: dict[str, Any]) -> dict[str, Any]:
    """Valores para abrir el formulario con lo que CentIA ya entendió."""
    draft = state["draft"]
    initial = {
        "kind": draft.get("kind"),
        "amount": draft.get("amount"),
        "date": draft.get("date"),
        "category": draft.get("category_id"),
        "account": draft.get("account_id"),
        "description": draft.get("description", ""),
        "source": "texto",
    }
    return {k: v for k, v in initial.items() if v}


# ---------------------------------------------------------------- reglas (sin IA)

_NUMBER = re.compile(r"(?<![\w/])(\d[\d.,]*)\s*(mil\b|k\b)?")
_AMOUNT_CUE = re.compile(r"\b(eran|fueron|son|monto|pesos|dolares|mil)\b|\$")
_KIND_WORDS = (
    (TxKind.TRANSFERENCIA_INTERNA, r"\b(transferi|transferencia|pase de|pase a|movi de)\b"),
    (TxKind.RETIRO_EFECTIVO, r"\b(saque del cajero|retire del cajero|retiro de cajero)\b"),
    (TxKind.PAGO_DEUDA, r"\b(cuota|prestamo|abono a la deuda)\b"),
    (TxKind.COMPRA_INVENTARIO, r"\b(materiales|insumos|materia prima)\b"),
    (TxKind.INGRESO, r"\b(me pagaron|cobre|recibi|ingreso|me depositaron|sueldo|salario|gane)\b"),
    (TxKind.GASTO, r"\b(gaste|pague|compre|gasto|me costo|costo)\b"),
)


def _parse_amount(raw: str, thousands: bool) -> Decimal | None:
    raw = raw.strip(".,")
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", raw):
        raw = re.sub(r"[.,]", "", raw)
    elif re.fullmatch(r"\d{1,3}([.,]\d{3})+[.,]\d{1,2}", raw):
        whole, cents = re.split(r"[.,](?=\d{1,2}$)", raw)
        raw = re.sub(r"[.,]", "", whole) + "." + cents
    else:
        raw = raw.replace(",", ".")
    try:
        value = Decimal(raw) * (1000 if thousands else 1)
    except InvalidOperation:
        return None
    return value if value > 0 else None


def interpret_by_rules(text: str, pending: list[str], context: dict[str, Any]) -> MovementTurn:
    """Entiende frases simples: monto, tipo, «ayer», y nombres de cuentas y categorías."""
    plain = normalize(text)
    lowered = text.lower()
    today = date.fromisoformat(context["hoy"])

    kind = next((k for k, pattern in _KIND_WORDS if re.search(pattern, plain)), None)
    if kind is None and pending[:1] == ["tipo"]:
        labels = {normalize(label): key for key, label in context["tipos"].items()}
        kind = labels.get(plain)

    amount = None
    if "monto" in pending or _AMOUNT_CUE.search(plain) or _AMOUNT_CUE.search(lowered):
        found = _NUMBER.search(lowered)
        if found:
            amount = _parse_amount(found.group(1), bool(found.group(2)))

    when = None
    if re.search(r"\banteayer\b|\bantes de ayer\b", plain):
        when = today - timedelta(days=2)
    elif re.search(r"\bayer\b", plain):
        when = today - timedelta(days=1)
    elif re.search(r"\bhoy\b", plain):
        when = today

    words = [w for w in plain.split() if len(w) >= 4]
    account = next(
        (
            name
            for name in context["cuentas"]
            if normalize(name) in plain or any(w in normalize(name).split() for w in words)
        ),
        None,
    )
    category = next((n for n in context["categorias"] if normalize(n) in plain), None)
    if category is None:
        category = next((SYNONYMS[w] for w in plain.split() if w in SYNONYMS), None)
    if category is None and pending[:1] == ["categoria"]:
        category = text
    return MovementTurn(tipo=kind, monto=amount, fecha=when, categoria=category, cuenta=account)


# ---------------------------------------------------------------- turno


def _history(state: dict[str, Any]) -> str:
    lines = [
        f"{NAME if m['rol'] == 'centia' else 'Persona'}: {m['texto']}"
        for m in state["messages"][-HISTORY - 1 : -1]
    ]
    return "\n".join(lines) or "(sin mensajes previos)"


def _readable(workspace: Workspace, draft: dict[str, Any]) -> dict[str, Any]:
    account = (
        Account.objects.for_workspace(workspace).filter(pk=draft["account_id"]).first()
        if draft.get("account_id")
        else None
    )
    category = (
        Category.objects.for_workspace(workspace).filter(pk=draft["category_id"]).first()
        if draft.get("category_id")
        else None
    )
    return {
        "tipo": draft.get("kind"),
        "monto": draft.get("amount"),
        "fecha": draft.get("date"),
        "cuenta": account.name if account else None,
        "categoria": category.name if category else None,
    }


def _summary(workspace: Workspace, state: dict[str, Any]) -> str:
    ready = proposal(workspace, state)
    if ready is None:
        return QUESTIONS["cuenta"]
    parts = [f"{ready['tipo'].lower()} de {fmt(ready['monto'], workspace.currency)}"]
    if ready["categoria"]:
        parts.append(f"en {ready['categoria'].name}")
    parts.append(f"con {ready['cuenta'].name}")
    parts.append(f"el {ready['fecha']:%d/%m/%Y}")
    return "Listo: " + " ".join(parts) + ". Revísalo y pulsa «Guardar»; si algo no es así, dímelo."


def take_turn(
    state: dict[str, Any], workspace: Workspace, user: User, text: str, today: date
) -> None:
    text = text.strip()[:MAX_TEXT]
    if not text:
        return
    draft = state["draft"]
    state["messages"].append({"rol": "usuario", "texto": text, "enlaces": []})
    state["turns"] += 1
    if state["turns"] > MAX_TURNS:
        _say(
            state,
            "Llevamos muchos mensajes. Te dejo lo que tengo en el formulario para terminarlo.",
            [{"texto": "Abrir el formulario", "url": _form_url(workspace)}],
        )
        return

    pending = missing(workspace, draft)
    if pending[:1] == ["categoria"] and _SKIP.search(normalize(text)):
        draft["category_skipped"] = True
        _reply(state, workspace, None)
        return

    allowed = kinds(workspace)
    accounts = _accounts(workspace)
    context = {
        "hoy": today.isoformat(),
        "tipos": allowed,
        "categorias": [c.name for c in _categories(workspace, None)],
        "cuentas": [a.name for a in accounts],
        "borrador": _readable(workspace, draft),
        "faltantes": pending,
        "historial": _history(state),
        "mensaje": text,
    }
    result = run_structured(
        workspace=workspace,
        user=user,
        purpose="centia_movimiento",
        prompt_name="centia_movimiento",
        context=context,
        schema=MovementTurn,
        fallback=lambda: interpret_by_rules(text, pending, context),
    )
    turn = result.data

    if turn.tipo in TRANSFER_KINDS:
        transfer_url = reverse("ledger:transfer", args=[workspace.pk])
        link = [{"texto": "Registrar transferencia", "url": transfer_url}]
        _say(
            state,
            "Eso parece mover dinero entre tus propias cuentas: no cuenta como gasto ni como "
            "ingreso y se registra aparte.",
            link,
        )
        return
    if turn.tipo:
        draft["kind"] = turn.tipo if turn.tipo in allowed else TxKind.GASTO
    if turn.monto:
        draft["amount"] = str(turn.monto.quantize(Decimal("0.01")))
    if turn.fecha:
        draft["date"] = turn.fecha.isoformat()
    draft.setdefault("date", today.isoformat())
    if turn.cuenta:
        account = match_account(workspace, turn.cuenta)
        if account:
            draft["account_id"] = str(account.pk)
    if not draft.get("account_id") and len(accounts) == 1:
        draft["account_id"] = str(accounts[0].pk)
    if turn.categoria:
        groups = (
            [CategoryGroup.INGRESO]
            if draft.get("kind") == TxKind.INGRESO
            else [g for g in CategoryGroup.values if g != CategoryGroup.INGRESO]
        )
        category = match_category(workspace, turn.categoria, *groups)
        if category:
            draft["category_id"] = str(category.pk)
            draft.pop("category_skipped", None)
    if turn.descripcion:
        draft["description"] = turn.descripcion[:140]
    elif "description" not in draft and state["turns"] == 1:
        draft["description"] = text[:140]
    _reply(state, workspace, turn.mensaje if result.from_ai else None)


def _reply(state: dict[str, Any], workspace: Workspace, ai_message: str | None) -> None:
    pending = missing(workspace, state["draft"])
    if not pending:
        _say(state, _summary(workspace, state))
        return
    if ai_message:
        _say(state, ai_message)
        return
    draft = state["draft"]
    noted = []
    if draft.get("kind"):
        noted.append(kinds(workspace).get(draft["kind"], draft["kind"]).lower())
    if draft.get("amount"):
        noted.append(f"de {fmt(Decimal(draft['amount']), workspace.currency)}")
    prefix = f"Anoté: {' '.join(noted)}. " if noted else ""
    _say(state, prefix + QUESTIONS[pending[0]])


def _form_url(workspace: Workspace) -> str:
    return reverse("ledger:new", args=[workspace.pk]) + "?centia=1"


# ---------------------------------------------------------------- guardar


def build_form(state: dict[str, Any], workspace: Workspace, client_uuid: str) -> QuickEntryForm:
    """Formulario rápido con el borrador: guardar pasa por la misma validación que a mano."""
    draft = state["draft"]
    return QuickEntryForm(
        {
            "kind": draft.get("kind", ""),
            "amount": draft.get("amount", ""),
            "category": draft.get("category_id", ""),
            "account": draft.get("account_id", ""),
            "date": draft.get("date", ""),
            "description": draft.get("description", ""),
            "client_uuid": client_uuid,
            "source": "texto",
        },
        workspace=workspace,
    )
