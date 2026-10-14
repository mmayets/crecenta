"""Asistente permanente: qué conviene hacer ahora, para qué sirve cada pantalla y cómo se hace algo.

- `suggestions`: recomendaciones calculadas con reglas a partir del estado real del espacio (los
  mismos servicios que alimentan los paneles). No usan IA ni inventan cifras.
- `page_tip`: una frase sobre la pantalla en la que está la persona.
- `answer`: responde «¿cómo hago…?». La IA redacta y elige destinos de un catálogo cerrado (nunca
  escribe direcciones); sin IA se buscan palabras clave en ese mismo catálogo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from django.urls import reverse

from apps.accounts.models import User
from apps.ai.schemas import HelpAnswer
from apps.ai.services.client import run_structured
from apps.alerts.models import Alert
from apps.business.models import Product
from apps.ledger.models import Transaction
from apps.reports.services.business_dashboard import (
    build_business_dashboard,
    build_seller_dashboard,
)
from apps.reports.services.dashboard import build_personal_dashboard
from apps.workspaces.models import Workspace
from apps.workspaces.permissions import FINANZAS, PROPIETARIO, VENDER, can

from .assistant import _plain
from .steps import get_state

URGENT, WARNING, INFO = "urgente", "aviso", "info"
SOON_DAYS = 3
QUIET_DAYS = 3
MAX_QUESTION = 300


@dataclass(frozen=True)
class Suggestion:
    key: str
    title: str
    text: str
    url: str
    action: str
    tone: str = INFO


def _url(name: str, workspace: Workspace, **kwargs: Any) -> str:
    return reverse(name, kwargs={"ws": workspace.pk, **kwargs})


# ---------------------------------------------------------------- recomendaciones


def suggestions(
    workspace: Workspace, user: User, role: str | None, today: date
) -> list[Suggestion]:
    """Recomendaciones ordenadas de más a menos urgente para este espacio y este rol."""
    if workspace.is_business and not can(role, FINANZAS):
        found = _seller(workspace, user, today)
    elif workspace.is_business:
        found = _business(workspace, user, role, today)
    else:
        found = _personal(workspace, user, today)
    order = {URGENT: 0, WARNING: 1, INFO: 2}
    return sorted(found, key=lambda s: order[s.tone])  # estable: respeta el orden de cada tono


def _pending_extraction(workspace: Workspace) -> Suggestion | None:
    if not get_state(workspace).pending_extraction:
        return None
    return Suggestion(
        "confirmar",
        "Tienes datos por confirmar",
        "Entendí lo que me contaste, pero todavía no está guardado.",
        _url("onboarding:confirm", workspace),
        "Revisar y guardar",
        WARNING,
    )


def _alerts(workspace: Workspace, alerts: list[Alert]) -> list[Suggestion]:
    urgent = [a for a in alerts if a.severity == Alert.Severity.ALTA]
    if urgent:
        return [
            Suggestion(
                "alerta",
                urgent[0].title,
                "Es tu alerta más urgente. Te explico por qué y qué puedes hacer.",
                _url("alerts:index", workspace),
                "Ver la alerta",
                URGENT,
            )
        ]
    if alerts:
        return [
            Suggestion(
                "alertas",
                "Tienes avisos por revisar",
                alerts[0].title,
                _url("alerts:index", workspace),
                "Ver avisos",
            )
        ]
    return []


def _ai_consent(user: User) -> list[Suggestion]:
    if user.ai_consent:
        return []
    return [
        Suggestion(
            "ia",
            "Activa el uso de IA",
            "Podrás dictar tus gastos, leer comprobantes con una foto y recibir tu plan explicado.",
            reverse("accounts:settings"),
            "Ir a Configuración",
        )
    ]


def _personal(workspace: Workspace, user: User, today: date) -> list[Suggestion]:
    d = build_personal_dashboard(workspace, today)
    found: list[Suggestion] = []
    pending = _pending_extraction(workspace)
    if pending:
        found.append(pending)
    if not d.ready:
        percent = d.profile.percent if d.profile else 0
        found.append(
            Suggestion(
                "perfil",
                "Completa tu perfil",
                f"Vas por el {percent} %. Con tus ingresos, pagos fijos y gastos esenciales "
                "puedo decirte cuánto puedes gastar.",
                _url("onboarding:index", workspace),
                "Completar",
                WARNING,
            )
        )
    elif d.availability and d.availability.is_short:
        found.append(
            Suggestion(
                "en_rojo",
                "Tu dinero no alcanza para lo planeado",
                "Lo que tienes no cubre los pagos pendientes y el ahorro del periodo. Revisa "
                "las alternativas de tu plan.",
                _url("planning:index", workspace),
                "Ver mi plan",
                URGENT,
            )
        )
    if d.pending_proposal:
        found.append(
            Suggestion(
                "propuesta",
                "Revisa tu propuesta de plan",
                "Hay un plan esperando que lo aceptes o lo ajustes.",
                _url("planning:detail", workspace, plan_id=d.pending_proposal.pk),
                "Revisar el plan",
                WARNING,
            )
        )
    elif d.ready and d.plan_source == "calculado":
        found.append(
            Suggestion(
                "plan",
                "Haz tu plan del mes",
                "Todavía no has aceptado un plan: las cifras que ves usan tus datos actuales.",
                _url("planning:index", workspace),
                "Crear mi plan",
            )
        )
    found += _alerts(workspace, d.alerts)
    soon = [p for p in d.upcoming if p.date <= today + timedelta(days=SOON_DAYS)]
    if soon:
        first = soon[0]
        when = "hoy" if first.date <= today else f"el {first.date:%d/%m}"
        found.append(
            Suggestion(
                "pago",
                f"Se acerca el pago de {first.name}",
                f"Vence {when}. Cuando lo pagues, regístralo para mantener tu disponible al día.",
                _url("ledger:new", workspace),
                "Registrar el pago",
                WARNING,
            )
        )
    found += _record_reminder(workspace, today, "ledger:new", "gastos")
    found += _ai_consent(user)
    if not Workspace.objects.filter(owner=user, kind=Workspace.Kind.BUSINESS).exists():
        found.append(
            Suggestion(
                "negocio",
                "¿Tienes un negocio?",
                "Crea su espacio aparte para saber cuánto vendes y cuánto ganas de verdad.",
                reverse("asistente:chat"),
                "Crear el espacio",
            )
        )
    return found


def _record_reminder(
    workspace: Workspace, today: date, url_name: str, what: str
) -> list[Suggestion]:
    last = (
        Transaction.objects.for_workspace(workspace)
        .order_by("-date")
        .values_list("date", flat=True)
        .first()
    )
    if last is None:
        title, text = (
            "Registra tu primer movimiento",
            "Con cada gasto o ingreso que anotes, tus cifras se vuelven más exactas.",
        )
    elif (today - last).days >= QUIET_DAYS:
        title, text = (
            f"Ponte al día con tus {what}",
            f"No registras nada desde el {last:%d/%m}. Anota lo de estos días para no perder "
            "la cuenta.",
        )
    else:
        return []
    return [Suggestion("registrar", title, text, _url(url_name, workspace), "Registrar")]


def _low_stock(workspace: Workspace) -> list[str]:
    return [
        p.name
        for p in Product.objects.for_workspace(workspace).filter(
            tracks_inventory=True, is_active=True, is_supply=False
        )
        if p.stock <= p.stock_minimum
    ]


def _business(workspace: Workspace, user: User, role: str | None, today: date) -> list[Suggestion]:
    d = build_business_dashboard(workspace, today)
    indicators, cash = d.snapshot.indicators, d.snapshot.cash
    found: list[Suggestion] = []
    pending = _pending_extraction(workspace)
    if pending:
        found.append(pending)
    if not d.ready:
        found.append(
            Suggestion(
                "perfil",
                "Completa los datos de tu negocio",
                f"Vas por el {d.profile.percent} %. Con lo que vendes, tus costos y gastos fijos "
                "puedo decirte cuánto ganas.",
                _url("onboarding:index", workspace),
                "Completar",
                WARNING,
            )
        )
    if not Product.objects.for_workspace(workspace).filter(is_active=True).exists():
        found.append(
            Suggestion(
                "productos",
                "Agrega lo que vendes",
                "Con el precio y el costo de cada producto calculo tu margen y te sugiero precios.",
                _url("business:product_new", workspace),
                "Agregar producto",
                WARNING,
            )
        )
    if cash.reserve.available < 0:
        found.append(
            Suggestion(
                "caja",
                "La caja no cubre los pagos de los próximos 30 días",
                "Revisa qué vence primero y qué puedes cobrar antes.",
                _url("business:payables", workspace),
                "Ver por pagar",
                URGENT,
            )
        )
    overdue = [r for r in d.receivables if r.due_date and r.due_date < today]
    if overdue:
        who = overdue[0].customer or overdue[0].concept
        found.append(
            Suggestion(
                "cobrar",
                "Tienes cobros vencidos",
                f"El más antiguo es de {who}. Cobrar a tiempo es lo que mantiene la caja sana.",
                _url("business:receivables", workspace),
                "Ver por cobrar",
                URGENT,
            )
        )
    due = [p for p in d.payables if p.due_date and p.due_date <= today + timedelta(days=SOON_DAYS)]
    if due:
        who = due[0].supplier or due[0].concept
        found.append(
            Suggestion(
                "pagar",
                "Tienes pagos a proveedores por vencer",
                f"El primero es a {who}, para el {due[0].due_date:%d/%m}.",
                _url("business:payables", workspace),
                "Ver por pagar",
                WARNING,
            )
        )
    if d.ready and indicators.operating_result < 0:
        found.append(
            Suggestion(
                "perdida",
                "Este mes vas en pérdida",
                "Tus gastos superan tu ganancia bruta. Revisa precios y costos de tus productos.",
                _url("business:pricing", workspace),
                "Revisar precios",
                WARNING,
            )
        )
    if d.pending_proposal:
        found.append(
            Suggestion(
                "propuesta",
                "Revisa la propuesta de plan del negocio",
                "Hay un plan esperando que lo aceptes o lo ajustes.",
                _url("planning:detail", workspace, plan_id=d.pending_proposal.pk),
                "Revisar el plan",
                WARNING,
            )
        )
    elif d.ready and d.accepted_plan is None:
        found.append(
            Suggestion(
                "plan",
                "Haz el plan del mes del negocio",
                "Fija cuánto quieres vender y ganar; te aviso cómo vas contra esa meta.",
                _url("planning:index", workspace),
                "Crear el plan",
            )
        )
    found += _alerts(workspace, d.alerts)
    low = _low_stock(workspace)
    if low:
        found.append(
            Suggestion(
                "inventario",
                "Hay productos por agotarse",
                f"{', '.join(low[:3])}{'…' if len(low) > 3 else ''}: están en su mínimo o menos.",
                _url("business:inventory", workspace),
                "Ver inventario",
                WARNING,
            )
        )
    found += _sales_today(workspace, user, today)
    if can(role, PROPIETARIO):
        found += _ai_consent(user)
    return found


def _sales_today(workspace: Workspace, user: User, today: date) -> list[Suggestion]:
    seller = build_seller_dashboard(workspace, user, today)
    if seller.sales_today_count:
        return []
    return [
        Suggestion(
            "vender",
            "Registra las ventas de hoy",
            "Aún no hay ventas anotadas hoy. Puedes registrarlas aunque no tengas conexión.",
            _url("business:sale_new", workspace),
            "Registrar venta",
        )
    ]


def _seller(workspace: Workspace, user: User, today: date) -> list[Suggestion]:
    found = _sales_today(workspace, user, today)
    seller = build_seller_dashboard(workspace, user, today)
    overdue = [r for r in seller.receivables if r.due_date and r.due_date < today]
    if overdue:
        who = overdue[0].customer or overdue[0].concept
        found.append(
            Suggestion(
                "cobrar",
                "Hay cobros vencidos",
                f"El más antiguo es de {who}.",
                _url("business:receivables", workspace),
                "Cobrar",
                URGENT,
            )
        )
    if seller.low_stock:
        names = ", ".join(name for name, _ in seller.low_stock[:3])
        found.append(
            Suggestion(
                "inventario",
                "Hay productos por agotarse",
                f"{names}: avisa para reponerlos.",
                _url("business:inventory", workspace),
                "Ver existencias",
                WARNING,
            )
        )
    return found


# ---------------------------------------------------------------- consejo por pantalla

PAGE_TIPS = {
    "espacio:dashboard": "Este es tu resumen. La tarjeta azul es la cifra que más importa hoy.",
    "ledger:movements": "Aquí está todo lo que entró y salió. Cambia de mes con las flechas.",
    "ledger:new": "Anota el monto y la categoría. Si prefieres, Sophia lo prepara por ti.",
    "ledger:sophia": "Dile a Sophia qué pasó; revisa la tarjeta del movimiento y pulsa «Guardar».",
    "ledger:transfer": "Mover dinero entre tus cuentas no cuenta como gasto ni como ingreso.",
    "ledger:accounts": "Tus cuentas y su saldo. Marca como ahorro las que no debes gastar.",
    "ledger:categories": "Las categorías deciden en qué grupo del plan cae cada gasto.",
    "planning:index": "Tu plan reparte tu ingreso entre pagos fijos, esenciales, ahorro y ocio.",
    "planning:detail": "Revisa cada línea. Puedes aceptar el plan, editarlo o ver alternativas.",
    "planning:edit": "Cambia los montos; te aviso si el plan deja de ser viable.",
    "planning:compare": "Compara dos versiones del plan lado a lado antes de decidir.",
    "alerts:index": "Cada alerta dice qué pasó, con qué datos y qué puedes hacer.",
    "alerts:rules": "Elige qué avisos quieres recibir y con qué umbral.",
    "receipts:index": "Sube la foto de un comprobante y lo convierto en un movimiento a revisar.",
    "receipts:detail": "Revisa lo que leí, sobre todo los campos resaltados, antes de confirmar.",
    "business:sales": "Tus ventas del periodo. Las de crédito cuentan al venderse, no al cobrarse.",
    "business:sale_new": "Elige productos y forma de pago. Sin conexión se guarda y se envía solo.",
    "business:products": "Cada producto con su precio, su costo y el margen que te deja.",
    "business:product_new": "Indica precio y costo; si lleva insumos, arma su receta.",
    "business:product_edit": "Indica precio y costo; si lleva insumos, arma su receta.",
    "business:pricing": "Te digo a cuánto vender para lograr el margen que buscas.",
    "business:inventory": "Existencias al costo. Los productos bajo su mínimo salen resaltados.",
    "business:purchases": "Tus compras de mercancía. Las de crédito quedan como cuenta por pagar.",
    "business:purchase_new": "Registra lo comprado; el inventario y el costo se actualizan solos.",
    "business:receivables": "Lo que te deben. Registra cada cobro, aunque sea parcial.",
    "business:payables": "Lo que debes a proveedores, ordenado por vencimiento.",
    "business:owner": "Retira solo lo que la caja permite después de pagos y reserva.",
    "business:reports": "Resultados por mes y archivos de apoyo para el 606 y el 607.",
    "espacio:settings": "Desde aquí llegas a todas las secciones y a tu configuración.",
    "espacio:team": "Invita a tu equipo. El vendedor registra ventas, sin ver costos ni ganancias.",
    "onboarding:step": "Responde lo que sepas; puedes omitir pasos y volver después.",
    "onboarding:conversation": "Cuéntalo con tus palabras; nada se guarda hasta que confirmes.",
    "onboarding:confirm": "Corrige lo que no entendí bien, sobre todo los campos resaltados.",
}


def page_tip(view_name: str) -> str | None:
    return PAGE_TIPS.get(view_name)


# ---------------------------------------------------------------- «¿cómo hago…?»


@dataclass(frozen=True)
class Destination:
    key: str
    label: str
    purpose: str
    url_name: str
    keywords: tuple[str, ...]
    perm: str = FINANZAS
    kind: str | None = None  # None = ambos tipos de espacio
    query: str = ""


P, B = Workspace.Kind.PERSONAL, Workspace.Kind.BUSINESS
DESTINATIONS = (
    Destination(
        "panel",
        "Panel",
        "ver el resumen del mes",
        "espacio:dashboard",
        ("resumen", "panel", "inicio", "como voy", "disponible"),
        VENDER,
    ),
    Destination(
        "gasto",
        "Registrar un gasto",
        "anotar un gasto o pago",
        "ledger:new",
        ("gasto", "gaste", "pague", "pago", "compre", "anotar", "registrar"),
    ),
    Destination(
        "ingreso",
        "Registrar un ingreso",
        "anotar dinero que entró",
        "ledger:new",
        ("ingreso", "cobre", "sueldo", "salario", "me pagaron"),
        kind=P,
        query="?tipo=ingreso",
    ),
    Destination(
        "transferir",
        "Transferir entre cuentas",
        "mover dinero entre cuentas propias",
        "ledger:transfer",
        (
            "transferir",
            "transferencia",
            "mover",
            "pasar",
            "paso dinero",
            "entre cuentas",
            "de una cuenta a otra",
        ),
        kind=P,
    ),
    Destination(
        "movimientos",
        "Movimientos",
        "ver, filtrar o eliminar movimientos",
        "ledger:movements",
        ("movimientos", "historial", "eliminar", "borrar", "lista"),
    ),
    Destination(
        "plan",
        "Plan",
        "crear, revisar o cambiar el plan del mes",
        "planning:index",
        ("plan", "presupuesto", "meta", "ahorro", "ahorrar", "repartir"),
    ),
    Destination(
        "alertas",
        "Alertas",
        "ver avisos y recomendaciones",
        "alerts:index",
        ("alerta", "alertas", "aviso", "avisos", "notificacion"),
    ),
    Destination(
        "reglas",
        "Reglas de alertas",
        "elegir qué avisos recibir",
        "alerts:rules",
        ("regla", "reglas", "umbral", "desactivar aviso"),
    ),
    Destination(
        "comprobantes",
        "Comprobantes",
        "subir la foto de una factura o recibo",
        "receipts:index",
        ("comprobante", "factura", "recibo", "foto", "ticket"),
    ),
    Destination(
        "cuentas",
        "Cuentas",
        "agregar o editar cuentas y saldos",
        "ledger:accounts",
        ("cuenta", "cuentas", "banco", "saldo", "efectivo", "tarjeta"),
    ),
    Destination(
        "categorias",
        "Categorías",
        "agregar o editar categorías",
        "ledger:categories",
        ("categoria", "categorias", "clasificar"),
    ),
    Destination(
        "perfil",
        "Mis datos",
        "cambiar ingresos, pagos fijos o datos del negocio",
        "onboarding:index",
        ("perfil", "ingresos", "compromisos", "deuda", "deudas", "datos"),
    ),
    Destination(
        "vender",
        "Registrar una venta",
        "anotar una venta",
        "business:sale_new",
        ("venta", "vender", "vendi", "factura", "cobrar venta"),
        VENDER,
        B,
    ),
    Destination(
        "ventas",
        "Ventas",
        "ver o anular ventas",
        "business:sales",
        ("ventas", "anular", "historial de ventas"),
        VENDER,
        B,
    ),
    Destination(
        "por_cobrar",
        "Por cobrar",
        "ver lo que deben los clientes y registrar cobros",
        "business:receivables",
        ("cobrar", "cobro", "fiado", "credito", "cliente", "me deben"),
        VENDER,
        B,
    ),
    Destination(
        "inventario",
        "Inventario",
        "ver existencias y ajustar inventario",
        "business:inventory",
        ("inventario", "existencia", "stock", "merma", "agotado"),
        VENDER,
        B,
    ),
    Destination(
        "productos",
        "Productos",
        "agregar productos, costos y recetas",
        "business:products",
        ("producto", "productos", "costo", "receta", "insumo"),
        kind=B,
    ),
    Destination(
        "precios",
        "Precios",
        "calcular a cuánto vender",
        "business:pricing",
        ("precio", "precios", "margen", "a cuanto", "rentable"),
        kind=B,
    ),
    Destination(
        "compras",
        "Registrar una compra",
        "anotar compra de mercancía",
        "business:purchase_new",
        ("compra", "compras", "mercancia", "proveedor"),
        kind=B,
    ),
    Destination(
        "por_pagar",
        "Por pagar",
        "ver deudas con proveedores y registrar pagos",
        "business:payables",
        ("pagar", "proveedor", "proveedores", "debo"),
        kind=B,
    ),
    Destination(
        "reportes",
        "Reportes",
        "ver resultados e ITBIS, descargar 606 y 607",
        "business:reports",
        ("reporte", "reportes", "itbis", "606", "607", "dgii", "ganancia", "resultados"),
        kind=B,
    ),
    Destination(
        "retiros",
        "Retiros y aportes",
        "sacar dinero del negocio o aportar",
        "business:owner",
        ("retiro", "retirar", "aporte", "sacar dinero"),
        PROPIETARIO,
        B,
    ),
    Destination(
        "equipo",
        "Equipo",
        "invitar personas y cambiar roles",
        "espacio:team",
        ("equipo", "invitar", "vendedor", "rol", "empleado"),
        PROPIETARIO,
        B,
    ),
    Destination(
        "ajustes",
        "Ajustes",
        "llegar a todas las secciones y a la configuración",
        "espacio:settings",
        ("ajustes", "configuracion", "privacidad", "exportar", "contrasena", "cerrar sesion"),
        VENDER,
    ),
)


def destinations(workspace: Workspace, role: str | None) -> dict[str, Destination]:
    return {
        d.key: d for d in DESTINATIONS if can(role, d.perm) and d.kind in (None, workspace.kind)
    }


def answer_by_rules(question: str, catalog: dict[str, Destination]) -> HelpAnswer:
    plain = _plain(question)
    scored = sorted(
        ((sum(1 for k in d.keywords if k in plain), d.key) for d in catalog.values()),
        key=lambda pair: -pair[0],
    )
    keys = [key for score, key in scored if score > 0][:3]
    if not keys:
        return HelpAnswer(
            mensaje="No estoy seguro de qué necesitas. Estas son las secciones más usadas; "
            "también puedes seguir mis recomendaciones de arriba.",
            destinos=[k for k in ("panel", "gasto", "vender", "plan") if k in catalog][:3],
        )
    return HelpAnswer(
        mensaje=f"Eso se hace en «{catalog[keys[0]].label}»: sirve para "
        f"{catalog[keys[0]].purpose}.",
        destinos=keys,
    )


def answer(
    workspace: Workspace, user: User, role: str | None, question: str, view_name: str, today: date
) -> dict[str, Any]:
    """Respuesta a una pregunta de uso: {"pregunta", "mensaje", "enlaces", "con_ia"}."""
    question = question.strip()[:MAX_QUESTION]
    catalog = destinations(workspace, role)

    def only_known(data: HelpAnswer) -> list[str]:
        unknown = [k for k in data.destinos if k not in catalog]
        return [f"destinos: «{k}» no está en el catálogo" for k in unknown]

    result = run_structured(
        workspace=workspace,
        user=user,
        purpose="asistente_ayuda",
        prompt_name="asistente_ayuda",
        context={
            "tipo": "negocio" if workspace.is_business else "personal",
            "rol": role or "",
            "pantalla": PAGE_TIPS.get(view_name, view_name or "desconocida"),
            "recomendaciones": [s.title for s in suggestions(workspace, user, role, today)[:4]],
            "catalogo": [
                {"clave": d.key, "nombre": d.label, "sirve_para": d.purpose}
                for d in catalog.values()
            ],
            "pregunta": question,
        },
        schema=HelpAnswer,
        fallback=lambda: answer_by_rules(question, catalog),
        validator=only_known,
    )
    return {
        "pregunta": question,
        "mensaje": result.data.mensaje,
        "enlaces": [
            {
                "texto": catalog[k].label,
                "url": _url(catalog[k].url_name, workspace) + catalog[k].query,
            }
            for k in result.data.destinos
            if k in catalog
        ],
        "con_ia": result.from_ai,
    }
