from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.alerts.services.evaluate import purchase_warnings
from apps.workspaces.mixins import workspace_required
from apps.workspaces.models import Workspace

from .forms import ReviewForm, UploadForm
from .models import Receipt
from .services.ingest import ingest_receipt
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
    if request.method == "POST" and form.is_valid():
        try:
            receipt = ingest_receipt(workspace, request.user, form.cleaned_data["file"])
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
