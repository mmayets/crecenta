from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.alerts.services.evaluate import purchase_warnings
from apps.core.ratelimit import hit
from apps.workspaces.mixins import workspace_required
from apps.workspaces.models import Workspace

from .forms import ReviewForm, UploadForm
from .models import Receipt
from .services.ingest import ingest_receipt
from .services.qr import parse as parse_qr
from .services.review import (
    ReceiptConfirmation,
    ReceiptError,
    confirm_receipt,
    discard_receipt,
    link_to_existing,
    reprocess,
)


def _get(workspace: Workspace, receipt_id) -> Receipt:
    try:
        return Receipt.objects.for_workspace(workspace).get(pk=receipt_id)
    except (Receipt.DoesNotExist, ValidationError, ValueError) as exc:
        raise Http404("Comprobante no encontrado") from exc


@workspace_required
@require_http_methods(["GET", "POST"])
def index(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    form = UploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and not hit(
        f"upload:{request.user.pk}", settings.UPLOAD_RATE_LIMITS
    ):
        form.add_error(None, "Subiste muchos comprobantes en poco tiempo. Intenta más tarde.")
    elif request.method == "POST" and form.is_valid():
        try:
            receipt = ingest_receipt(
                workspace, request.user, form.cleaned_data["file"], request.POST.get("qr_texto", "")
            )
        except ValidationError as exc:
            form.add_error("file", exc.messages)
        else:
            return redirect("receipts:detail", ws=workspace.pk, receipt_id=receipt.pk)
    receipts = Receipt.objects.for_workspace(workspace)[:30]
    status = 400 if request.method == "POST" else 200
    return render(
        request,
        "receipts/index.html",
        {"workspace": workspace, "form": form, "receipts": receipts},
        status=status,
    )


@workspace_required
@require_http_methods(["GET", "POST"])
def detail(request: HttpRequest, workspace: Workspace, receipt_id) -> HttpResponse:
    receipt = _get(workspace, receipt_id)
    form = ReviewForm(receipt, request.POST or None) if receipt.is_reviewable else None
    if request.method == "POST":
        if form is None:
            messages.error(request, "Este comprobante ya no se puede modificar.")
            return redirect("receipts:detail", ws=workspace.pk, receipt_id=receipt.pk)
        if form.is_valid():
            data = form.cleaned_data
            try:
                confirm_receipt(
                    receipt,
                    request.user,
                    ReceiptConfirmation(
                        account=data["account"],
                        date=data["date"],
                        amount=data["amount"],
                        description=data["description"],
                        category=data["category"],
                        rubro=data.get("rubro") or "",
                        invoice_number=data.get("invoice_number") or "",
                    ),
                )
            except (ValidationError, ReceiptError) as exc:
                form.add_error(None, str(exc))
            else:
                messages.success(request, "Gasto registrado con su comprobante.")
                return redirect("receipts:index", ws=workspace.pk)
    warnings = []
    if form is not None and receipt.extracted.get("total"):
        warnings = purchase_warnings(
            workspace, Decimal(str(receipt.extracted["total"])), form.initial.get("category")
        )
    template = (
        "receipts/_detail.html" if request.headers.get("HX-Request") else "receipts/detail.html"
    )
    return render(
        request,
        template,
        {"workspace": workspace, "receipt": receipt, "form": form, "warnings": warnings},
    )


@workspace_required
@require_POST
def link(request: HttpRequest, workspace: Workspace, receipt_id) -> HttpResponse:
    try:
        link_to_existing(_get(workspace, receipt_id), request.user)
        messages.success(request, "Comprobante vinculado al movimiento existente.")
    except ReceiptError as exc:
        messages.error(request, str(exc))
    return redirect("receipts:index", ws=workspace.pk)


@workspace_required
@require_POST
def discard(request: HttpRequest, workspace: Workspace, receipt_id) -> HttpResponse:
    try:
        discard_receipt(_get(workspace, receipt_id), request.user)
        messages.info(request, "Comprobante descartado.")
    except ReceiptError as exc:
        messages.error(request, str(exc))
    return redirect("receipts:index", ws=workspace.pk)


@workspace_required
@require_POST
def retry(request: HttpRequest, workspace: Workspace, receipt_id) -> HttpResponse:
    receipt = _get(workspace, receipt_id)
    try:
        reprocess(receipt, request.user)
    except ReceiptError as exc:
        messages.error(request, str(exc))
    return redirect("receipts:detail", ws=workspace.pk, receipt_id=receipt.pk)


@workspace_required
@require_GET
def file(request: HttpRequest, workspace: Workspace, receipt_id) -> FileResponse:
    """Descarga autenticada: el archivo solo se entrega a miembros del espacio."""
    receipt = _get(workspace, receipt_id)
    extension = receipt.file.name.rsplit(".", 1)[-1]
    response = FileResponse(
        receipt.file.open("rb"),
        content_type=receipt.content_type,
        as_attachment=request.GET.get("descargar") == "1",
        filename=f"comprobante-{receipt.created_at:%Y%m%d}.{extension}",
    )
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response


# Clave de sesión del borrador que deja un QR escaneado para el formulario de registro.
QR_DRAFT = "factura_qr:{}"


@workspace_required
@require_POST
def scan_qr(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    """El teléfono leyó el QR de una factura: se abre el registro con sus datos para confirmar."""
    invoice = parse_qr(request.POST.get("texto", ""))
    if not invoice.found:
        messages.error(
            request,
            "No reconocí una factura en ese código QR. Sube la foto o registra el gasto a mano.",
        )
        return redirect("receipts:index", ws=workspace.pk)
    request.session[QR_DRAFT.format(workspace.pk)] = invoice.as_json()
    messages.success(request, f"Leí la factura {invoice.numero or ''}. Revisa y guarda el gasto.")
    return redirect(reverse("ledger:new", kwargs={"ws": workspace.pk}) + "?factura=1")
