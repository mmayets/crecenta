"""Asistente que guía, en un chat, la creación de espacios y su primer llenado.

Etapas: `chat` (reúne uso, nombre del negocio y moneda) → `resumen` (la persona confirma con un
botón) → `llenado` (describe cada espacio creado; la extracción pasa por la pantalla de
confirmación del onboarding) → `fin`.

La IA solo propone lo que entendió de cada mensaje: el servidor valida el borrador, decide la
etapa y es el único que crea espacios. Sin IA (sin consentimiento, límite o falla) el borrador se
interpreta con reglas simples, así que crear el espacio nunca depende del proveedor.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta
from typing import Any

from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.ai.schemas import AssistantTurn
from apps.ai.services.client import AIUnavailable, run_structured
from apps.core.money import CURRENCY_CHOICES
from apps.onboarding.models import AssistantSession
from apps.workspaces.forms import UsageForm
from apps.workspaces.models import Workspace
from apps.workspaces.services.workspaces import DEFAULT_NAMES, create_workspaces_for_usage

from .business_conversational import extract_business_from_text
from .conversational import extract_from_text
from .steps import get_state

Stage = AssistantSession.Stage

MAX_TURNS = 40
MAX_CHAT_TEXT = 600
MAX_FILL_TEXT = 4000
HISTORY = 8
SESSION_DAYS = 7
FIELDS = ("uso", "nombre_negocio", "moneda", "moneda_negocio")
KINDS_BY_USAGE = {
    "persona": [Workspace.Kind.PERSONAL],
    "negocio": [Workspace.Kind.BUSINESS],
    "ambos": [Workspace.Kind.PERSONAL, Workspace.Kind.BUSINESS],
}
CURRENCY_LABELS = dict(CURRENCY_CHOICES)

QUESTIONS = {
    "uso": "¿Qué quieres organizar: tu dinero personal, tu negocio o ambos?",
    "nombre_negocio": "¿Cómo se llama tu negocio?",
    "moneda": "¿En qué moneda manejas tu dinero: pesos dominicanos o dólares?",
}
QUICK_REPLIES = {
    "uso": ["Mi dinero personal", "Mi negocio", "Ambos"],
    "nombre_negocio": [],
    "moneda": ["Pesos (RD$)", "Dólares (US$)"],
}
FILL_PROMPTS = {
    Workspace.Kind.PERSONAL: (
        "Cuéntame con tus palabras cuánto cobras y cada cuánto, qué cuentas tienes, qué pagas "
        "fijo cada mes y cuánto gastas en comida y transporte. Te muestro lo que entendí antes "
        "de guardar."
    ),
    Workspace.Kind.BUSINESS: (
        "Cuéntame qué vendes, a qué precio, cuánto te cuesta, cuántos vendes al mes y los "
        "gastos fijos del negocio. Te muestro lo que entendí antes de guardar."
    ),
}


# ---------------------------------------------------------------- sesión


def active_session(user: User) -> AssistantSession | None:
    limit = timezone.now() - timedelta(days=SESSION_DAYS)
    return AssistantSession.objects.filter(user=user, updated_at__gte=limit).first()


def start(user: User) -> AssistantSession:
    """Empieza de cero: una sola conversación por persona."""
    AssistantSession.objects.filter(user=user).delete()
    session = AssistantSession(user=user)
    name = user.first_name.strip()
    owned = _owned(user)
    greeting = f"¡Hola{', ' + name if name else ''}! Soy Sophia, tu asistente en Crecenta. "
    if owned:
        names = ", ".join(f"«{w.name}»" for w in owned)
        session.say(f"{greeting}Ya tienes {names}. ¿Qué espacio nuevo quieres crear?")
    else:
        session.say(f"{greeting}En un par de preguntas dejo listo tu espacio. {QUESTIONS['uso']}")
    session.save()
    return session


def get_or_start(user: User) -> AssistantSession:
    return active_session(user) or start(user)


def _owned(user: User) -> list[Workspace]:
    return list(Workspace.objects.filter(owner=user).order_by("created_at"))


# ---------------------------------------------------------------- borrador


def kinds_to_create(user: User, draft: dict[str, Any]) -> list[str]:
    """Tipos de espacio que se crearían (misma regla que `create_workspaces_for_usage`)."""
    owned = {w.kind for w in _owned(user)}
    return [k for k in KINDS_BY_USAGE.get(draft.get("uso") or "", []) if k not in owned]


def missing(user: User, draft: dict[str, Any]) -> list[str]:
    if not draft.get("uso"):
        return ["uso"]
    pending = []
    if Workspace.Kind.BUSINESS in kinds_to_create(user, draft) and not draft.get("nombre_negocio"):
        pending.append("nombre_negocio")
    if not draft.get("moneda"):
        pending.append("moneda")
    return pending


def proposal(session: AssistantSession) -> list[dict[str, str]]:
    """Lo que se va a crear, para el resumen: [{"tipo", "nombre", "moneda"}]."""
    draft = session.draft
    rows = []
    for kind in kinds_to_create(session.user, draft):
        business = kind == Workspace.Kind.BUSINESS
        currency = (draft.get("moneda_negocio") if business else None) or draft.get("moneda")
        rows.append(
            {
                "tipo": Workspace.Kind(kind).label,
                "nombre": draft.get("nombre_negocio") if business else DEFAULT_NAMES[kind],
                "moneda": CURRENCY_LABELS.get(currency or "", "—"),
            }
        )
    return rows


def quick_replies(session: AssistantSession) -> list[str]:
    if session.stage != Stage.CHAT:
        return []
    pending = missing(session.user, session.draft)
    return QUICK_REPLIES[pending[0]] if pending else []


def _plain(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


_BOTH = re.compile(r"\b(ambos|ambas|los dos|las dos|las dos cosas)\b")
_BUSINESS = re.compile(r"\b(negocio|emprendimiento|empresa|tienda|colmado|vendo|ventas)\b")
_PERSONAL = re.compile(
    r"\b(personal|personales|persona|mi dinero|mis finanzas|mis gastos|mi sueldo|mi salario)\b"
)
_USD = re.compile(r"dolar|usd|us\$")
_DOP = re.compile(r"peso|dop|rd\$")
_NAME = re.compile(r"(?:se llama|llamad[oa]|nombre es|nombre:)\s+([^.,;\n]+)", re.IGNORECASE)


def interpret_by_rules(text: str, pending: list[str]) -> AssistantTurn:
    """Respaldo sin IA: entiende respuestas simples («mi negocio», «dólares», un nombre)."""
    plain = _plain(text)
    asking_name = pending[:1] == ["nombre_negocio"]
    currency = "USD" if _USD.search(plain) else "DOP" if _DOP.search(plain) else None
    usage = None
    if not asking_name:
        business, personal = _BUSINESS.search(plain), _PERSONAL.search(plain)
        if _BOTH.search(plain) or (business and personal):
            usage = "ambos"
        elif business:
            usage = "negocio"
        elif personal:
            usage = "persona"
    name = None
    named = _NAME.search(text)
    if named:
        name = named.group(1)
    elif asking_name and currency is None:
        name = text
    if name:
        name = name.strip(" \"'«»“”.")[:80] or None
    return AssistantTurn(uso=usage, nombre_negocio=name, moneda=currency)


def _history(session: AssistantSession) -> str:
    lines = [
        f"{'Sophia' if m['rol'] == 'asistente' else 'Persona'}: {m['texto']}"
        for m in session.messages[-HISTORY - 1 : -1]
    ]
    return "\n".join(lines) or "(sin mensajes previos)"


def _draft_turn(session: AssistantSession, text: str) -> None:
    user, draft = session.user, session.draft
    pending = missing(user, draft)
    result = run_structured(
        workspace=None,
        user=user,
        purpose="asistente_espacios",
        prompt_name="asistente_espacios",
        context={
            "existentes": [{"nombre": w.name, "tipo": w.kind} for w in _owned(user)],
            "borrador": {f: draft.get(f) for f in FIELDS},
            "faltantes": pending,
            "historial": _history(session),
            "mensaje": text,
        },
        schema=AssistantTurn,
        fallback=lambda: interpret_by_rules(text, pending),
    )
    turn = result.data
    for name in FIELDS:
        value = getattr(turn, name)
        if value:
            draft[name] = value

    if draft.get("uso") and not kinds_to_create(user, draft):
        draft.pop("uso")
        session.stage = Stage.CHAT
        session.say(
            "Ese espacio ya lo tienes. Puedes abrirlo, o decirme si quieres crear otro distinto.",
            [
                {"texto": f"Abrir «{w.name}»", "url": reverse("espacio:dashboard", args=[w.pk])}
                for w in _owned(user)
            ],
        )
        return

    pending = missing(user, draft)
    if pending:
        session.stage = Stage.CHAT
        reply = turn.mensaje if result.from_ai and turn.mensaje else QUESTIONS[pending[0]]
        session.say(reply)
        return
    session.stage = Stage.SUMMARY
    parts = [f"{p['tipo'].lower()} «{p['nombre']}» en {p['moneda']}" for p in proposal(session)]
    session.say(
        "Tengo todo. Voy a crear: "
        + " y ".join(parts)
        + ". Si está bien, pulsa «Crear»; si no, dime qué cambio."
    )


# ---------------------------------------------------------------- crear


def confirm(session: AssistantSession) -> list[Workspace]:
    """Crea los espacios del borrador. Solo se llama desde el botón «Crear»."""
    user, draft = session.user, session.draft
    if session.stage != Stage.SUMMARY or missing(user, draft):
        return []
    form = UsageForm(
        {
            "usage": draft.get("uso"),
            "currency": draft.get("moneda"),
            "business_name": draft.get("nombre_negocio") or "",
            "business_currency": draft.get("moneda_negocio") or "",
        }
    )
    if not form.is_valid():
        session.stage = Stage.CHAT
        session.say("Hay un dato que no pude usar. " + QUESTIONS["uso"])
        session.draft = {}
        session.save()
        return []
    data = form.cleaned_data
    created = create_workspaces_for_usage(
        user,
        data["usage"],
        currency=data["currency"],
        business_name=data["business_name"] or None,
        business_currency=data["business_currency"] or None,
    )
    if not created:
        session.stage = Stage.DONE
        session.say("Esos espacios ya existían, así que no creé nada nuevo.")
        session.save()
        return []
    session.created_ids = [str(w.pk) for w in created]
    session.queue = list(session.created_ids)
    session.stage = Stage.FILLING
    names = " y ".join(f"«{w.name}»" for w in created)
    session.say(f"¡Listo! Creé {names}. Ahora vamos a ponerle datos a «{created[0].name}».")
    session.say(FILL_PROMPTS[Workspace.Kind(created[0].kind)])
    session.save()
    return created


# ---------------------------------------------------------------- llenado


def current_workspace(session: AssistantSession) -> Workspace | None:
    """Primer espacio de la cola que sigue existiendo y es de la persona."""
    while session.queue:
        workspace = Workspace.objects.filter(owner=session.user, pk=session.queue[0]).first()
        if workspace is not None:
            return workspace
        session.queue.pop(0)
    return None


def created_workspaces(session: AssistantSession) -> list[Workspace]:
    by_id = {
        str(w.pk): w
        for w in Workspace.objects.filter(owner=session.user, pk__in=session.created_ids)
    }
    return [by_id[i] for i in session.created_ids if i in by_id]


def _count(items: list[Any], singular: str, plural: str) -> str | None:
    if not items:
        return None
    return f"{len(items)} {singular if len(items) == 1 else plural}"


def _fill_turn(session: AssistantSession, text: str, today: date) -> None:
    workspace = current_workspace(session)
    if workspace is None:
        _finish(session)
        return
    step_form = {
        "texto": "Usar el formulario paso a paso",
        "url": reverse("onboarding:index", args=[workspace.pk]),
    }
    try:
        if workspace.is_business:
            business = extract_business_from_text(workspace, session.user, text, today)
            found = [
                _count(business.productos, "producto", "productos"),
                _count(business.gastos, "gasto fijo", "gastos fijos"),
            ]
            data = business.model_dump(mode="json")
        else:
            personal = extract_from_text(workspace, session.user, text, today)
            found = [
                _count(personal.ingresos, "ingreso", "ingresos"),
                _count(personal.cuentas, "cuenta", "cuentas"),
                _count(personal.compromisos, "pago fijo", "pagos fijos"),
                _count(personal.esenciales, "gasto esencial", "gastos esenciales"),
                _count(personal.deudas, "deuda", "deudas"),
                _count(personal.metas_ahorro, "meta de ahorro", "metas de ahorro"),
            ]
            data = personal.model_dump(mode="json")
    except AIUnavailable as exc:
        session.say(f"{exc} Mientras tanto puedes seguir con el formulario.", [step_form])
        return
    found = [f for f in found if f]
    if not found:
        session.say(
            "No encontré datos que pueda guardar en ese mensaje. Prueba con cifras concretas, "
            "por ejemplo: «cobro 50 mil el día 30 y pago 18 mil de alquiler el 5».",
            [step_form],
        )
        return
    state = get_state(workspace)
    state.pending_extraction = data
    state.save()
    session.say(
        f"Para «{workspace.name}» entendí: {', '.join(found)}. Revísalo y guárdalo; nada se "
        "guarda hasta que confirmes.",
        [{"texto": "Revisar y guardar", "url": reverse("onboarding:confirm", args=[workspace.pk])}],
    )


def _advance(session: AssistantSession) -> None:
    """Pasa al siguiente espacio de la cola o termina."""
    session.queue = session.queue[1:]
    following = current_workspace(session)
    if following is None:
        _finish(session)
        return
    session.say(f"Sigamos con «{following.name}».")
    session.say(FILL_PROMPTS[Workspace.Kind(following.kind)])


def _finish(session: AssistantSession) -> None:
    session.stage = Stage.DONE
    links = []
    for workspace in created_workspaces(session):
        links.append(
            {
                "texto": f"Ir a «{workspace.name}»",
                "url": reverse("espacio:dashboard", args=[workspace.pk]),
            }
        )
        links.append(
            {
                "texto": f"Hacer el plan de «{workspace.name}»",
                "url": reverse("onboarding:done", args=[workspace.pk]),
            }
        )
    session.say(
        "¡Todo listo! Ya puedes entrar a tus espacios. Cuando quieras, hago el plan del mes con "
        "tus números.",
        links,
    )


def sync(session: AssistantSession) -> None:
    """Al volver al chat: si el espacio en curso ya tiene datos guardados, avanza."""
    if session.stage != Stage.FILLING:
        return
    workspace = current_workspace(session)
    if workspace is None:
        _finish(session)
    else:
        state = get_state(workspace)
        if not state.answered_steps or state.pending_extraction:
            return
        session.say(f"Guardé los datos de «{workspace.name}».")
        _advance(session)
    session.save()


def skip(session: AssistantSession) -> None:
    if session.stage != Stage.FILLING:
        return
    workspace = current_workspace(session)
    if workspace is not None:
        session.say(f"De acuerdo, «{workspace.name}» lo completas cuando quieras desde Ajustes.")
    _advance(session)
    session.save()


def after_confirm_url(user: User, workspace: Workspace) -> str | None:
    """Tras confirmar datos en el onboarding: vuelve al chat si ese espacio estaba en la cola."""
    session = active_session(user)
    if session is None or session.stage != Stage.FILLING:
        return None
    return reverse("asistente:chat") if str(workspace.pk) in session.queue else None


# ---------------------------------------------------------------- turno


def take_turn(session: AssistantSession, text: str, today: date | None = None) -> None:
    filling = session.stage == Stage.FILLING
    text = text.strip()[: MAX_FILL_TEXT if filling else MAX_CHAT_TEXT]
    if not text or session.stage == Stage.DONE:
        return
    session.hear(text)
    session.turns += 1
    if session.turns > MAX_TURNS:
        session.say(
            "Llevamos muchos mensajes en esta conversación. Puedes terminar con el formulario "
            "o empezar una conversación nueva.",
            [{"texto": "Usar el formulario", "url": reverse("workspaces:usage")}],
        )
    elif filling:
        _fill_turn(session, text, today or timezone.localdate())
    else:
        _draft_turn(session, text)
    session.save()
