import json
import uuid
from datetime import date, timedelta

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.ai.services.client import AIUnavailable
from apps.alerts.services.evaluate import purchase_warnings
from apps.business.services.sales import undo_settlement
from apps.core.money import amount_or_zero
from apps.core.ratelimit import hit
from apps.onboarding.forms import AccountForm
from apps.workspaces.mixins import workspace_required
from apps.workspaces.models import Workspace
from apps.workspaces.services.transfers import delete_transfer, transfer_for

from .choices import Direction, TxStatus
from .forms import CategoryForm, FreeTextForm, QuickEntryForm, TransferForm
from .models import Account, Category, Transaction
from .services.balances import balances_by_account
from .services.quick_entry import parse_free_text
from .services.sync import parse_item, sync_batch, upsert_from_client

FIELD_FOR_KEY = {
    "account_id": "account",
    "category_id": "category",
    "to_account_id": "to_account",
    "client_uuid": None,
    "date": "date",
    "amount": "amount",
    "kind": "kind",
    "direction": "kind",
    "source": None,
    "category": "category",
    "account": "account",
}


@workspace_required
@require_POST
def sync(request: HttpRequest, workspace: Workspace) -> JsonResponse:
    """Recibe movimientos registrados sin conexión: {"items": [...]}. Idempotente por client_uuid.

    Responde 200 con el resultado de cada elemento (creado / existente / error) para que el
    dispositivo elimine de su cola los que ya quedaron guardados.
    """
    if not hit(f"sync:{request.user.pk}", settings.SYNC_RATE_LIMITS):
        return JsonResponse({"error": "Demasiados envíos. Intenta en un momento."}, status=429)
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "JSON inválido"}, status=400)
    items = body.get("items") if isinstance(body, dict) else None
    if not isinstance(items, list):
        return JsonResponse({"error": "Se espera {'items': [...]}"}, status=400)
    try:
        results = sync_batch(workspace, request.user, items)
    except ValidationError as exc:
        return JsonResponse({"error": exc.messages[0]}, status=400)
    return JsonResponse({"resultados": results})


def _month(request: HttpRequest) -> tuple[date, date]:
    today = timezone.localdate()
    try:
        year, month = (int(x) for x in request.GET.get("mes", "").split("-"))
        start = date(year, month, 1)
    except ValueError:
        start = today.replace(day=1)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return start, end


@workspace_required
@require_GET
def movements(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    start, end = _month(request)
    qs = (
        Transaction.objects.for_workspace(workspace)
        .filter(date__range=(start, end))
        .select_related("category", "account")
    )
    category = request.GET.get("categoria")
    if category:
        qs = qs.filter(category_id=category) if _is_uuid(category) else qs.none()
    confirmed = qs.filter(status=TxStatus.CONFIRMADO)
    totals = confirmed.aggregate(
        entradas=Sum("amount", filter=Q(direction=Direction.IN, kind__in=["ingreso", "venta"])),
        salidas=Sum(
            "amount",
            filter=Q(
                direction=Direction.OUT, kind__in=["gasto", "pago_deuda", "compra_inventario"]
            ),
        ),
    )
    previous = (start - timedelta(days=1)).strftime("%Y-%m")
    following = (end + timedelta(days=1)).strftime("%Y-%m")
    return render(
        request,
        "ledger/movements.html",
        {
            "workspace": workspace,
            "transactions": qs.order_by("-date", "-created_at")[:300],
            "start": start,
            "previous": previous,
            "following": following,
            "totals": totals,
            "categories": Category.objects.for_workspace(workspace).filter(is_archived=False),
            "selected_category": category or "",
        },
    )


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def _save_quick(request: HttpRequest, workspace: Workspace, form: QuickEntryForm) -> bool:
    try:
        item = parse_item(workspace, form.as_sync_payload())
        result = upsert_from_client(workspace, request.user, item)
    except ValidationError as exc:
        for key, errors in exc.message_dict.items():
            form.add_error(FIELD_FOR_KEY.get(key), errors)
        return False
    if result.created:
        messages.success(request, "Movimiento registrado.")
    else:
        messages.info(request, "Este movimiento ya estaba registrado.")
    return True


@workspace_required
@require_http_methods(["GET", "POST"])
def new(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    initial = {"kind": request.GET.get("tipo", "gasto")}
    form = QuickEntryForm(request.POST or None, workspace=workspace, initial=initial)
    if request.method == "POST" and form.is_valid() and _save_quick(request, workspace, form):
        return redirect("ledger:movements", ws=workspace.pk)
    return render(
        request,
        "ledger/new.html",
        {"workspace": workspace, "form": form, "text_form": FreeTextForm()},
        status=400 if request.method == "POST" else 200,
    )


@workspace_required
@require_POST
def from_text(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    text_form = FreeTextForm(request.POST)
    if not text_form.is_valid():
        messages.error(request, "Escribe el movimiento que quieres registrar.")
        return redirect("ledger:new", ws=workspace.pk)
    try:
        draft = parse_free_text(
            workspace, request.user, text_form.cleaned_data["texto"], timezone.localdate()
        )
    except AIUnavailable as exc:
        messages.error(request, f"{exc} Puedes registrarlo con el formulario.")
        return redirect("ledger:new", ws=workspace.pk)
    initial = {**draft.initial(), "source": text_form.cleaned_data.get("via") or "texto"}
    if draft.kind not in ("gasto", "ingreso", "pago_deuda"):
        messages.info(request, "Parece una transferencia entre tus cuentas: revísala aquí.")
        return redirect("ledger:transfer", ws=workspace.pk)
    form = QuickEntryForm(workspace=workspace, initial=initial)
    form.highlight(draft.doubtful)
    return render(
        request,
        "ledger/new.html",
        {"workspace": workspace, "form": form, "text_form": text_form, "from_ai": True},
    )


@workspace_required
@require_http_methods(["GET", "POST"])
def transfer(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    form = TransferForm(request.POST or None, workspace=workspace)
    if request.method == "POST" and form.is_valid():
        try:
            upsert_from_client(
                workspace, request.user, parse_item(workspace, form.as_sync_payload())
            )
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        else:
            messages.success(request, "Transferencia registrada. No cuenta como gasto.")
            return redirect("ledger:movements", ws=workspace.pk)
    return render(
        request,
        "ledger/transfer.html",
        {"workspace": workspace, "form": form},
        status=400 if request.method == "POST" else 200,
    )


@workspace_required
@require_POST
def delete(request: HttpRequest, workspace: Workspace, tx_id) -> HttpResponse:
    try:
        tx = Transaction.objects.for_workspace(workspace).get(pk=tx_id)
    except (Transaction.DoesNotExist, ValidationError) as exc:
        raise Http404 from exc
    back = redirect("ledger:movements", ws=workspace.pk)
    # Movimientos vinculados: se borran con su flujo para no dejar deudas o espejos descuadrados.
    if tx.sale_id:
        messages.error(request, "Este movimiento es de una venta: anula la venta desde Ventas.")
        return back
    linked = transfer_for(tx)
    if linked is not None:
        delete_transfer(request.user, linked)  # type: ignore[arg-type]
        messages.info(request, "Se eliminaron los dos movimientos de la transferencia.")
        return back
    if tx.receivable_id or tx.payable_id:
        undo_settlement(workspace, tx)
        messages.info(request, "Movimiento eliminado; su monto volvió al saldo pendiente.")
        return back
    with transaction.atomic():
        pair = tx.transfer_pair
        Transaction.objects.filter(pk__in=[tx.pk] + ([pair.pk] if pair else [])).update(
            transfer_pair=None
        )
        Transaction.objects.filter(pk__in=[tx.pk] + ([pair.pk] if pair else [])).delete()
    messages.info(request, "Movimiento eliminado.")
    return back


@workspace_required
@require_POST
def warnings(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    """Avisos previos mientras se llena el formulario (htmx)."""
    amount = amount_or_zero(request.POST.get("amount"))
    category = None
    category_id = request.POST.get("category")
    if category_id and _is_uuid(category_id):
        category = Category.objects.for_workspace(workspace).filter(pk=category_id).first()
    items = []
    if amount > 0 and request.POST.get("kind", "gasto") != "ingreso":
        items = purchase_warnings(workspace, amount, category)
    return render(request, "ledger/_warnings.html", {"warnings": items})


# ---------------------------------------------------------------- ajustes: cuentas y categorías


@workspace_required
@require_http_methods(["GET", "POST"])
def accounts(request: HttpRequest, workspace: Workspace, account_id=None) -> HttpResponse:
    instance = None
    if account_id:
        instance = Account.objects.for_workspace(workspace).filter(pk=account_id).first()
        if instance is None:
            raise Http404
    form = AccountForm(request.POST or None, instance=instance, workspace=workspace)
    if request.method == "POST":
        if "archivar" in request.POST and instance:
            instance.is_archived = not instance.is_archived
            instance.save(update_fields=["is_archived", "updated_at"])
            return redirect("ledger:accounts", ws=workspace.pk)
        if form.is_valid():
            form.save()
            messages.success(request, "Cuenta guardada.")
            return redirect("ledger:accounts", ws=workspace.pk)
    balances = balances_by_account(workspace)
    rows = [
        (a, balances.get(a.pk, a.opening_balance)) for a in Account.objects.for_workspace(workspace)
    ]
    return render(
        request,
        "ledger/accounts.html",
        {"workspace": workspace, "form": form, "rows": rows, "editing": instance},
    )


@workspace_required
@require_http_methods(["GET", "POST"])
def categories(request: HttpRequest, workspace: Workspace, category_id=None) -> HttpResponse:
    instance = None
    if category_id:
        instance = Category.objects.for_workspace(workspace).filter(pk=category_id).first()
        if instance is None:
            raise Http404
    form = CategoryForm(request.POST or None, instance=instance, workspace=workspace)
    if request.method == "POST":
        if "archivar" in request.POST and instance:
            instance.is_archived = not instance.is_archived
            instance.save(update_fields=["is_archived", "updated_at"])
            return redirect("ledger:categories", ws=workspace.pk)
        if form.is_valid():
            form.save()
            messages.success(request, "Categoría guardada.")
            return redirect("ledger:categories", ws=workspace.pk)
    return render(
        request,
        "ledger/categories.html",
        {
            "workspace": workspace,
            "form": form,
            "editing": instance,
            "categories": Category.objects.for_workspace(workspace).order_by("group", "name"),
        },
    )
