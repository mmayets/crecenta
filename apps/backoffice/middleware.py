"""Auditoría automática: registra cada acción (POST, PUT, PATCH, DELETE) y cada página visitada
por una persona con sesión. Así ninguna vista nueva queda fuera de la auditoría."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from .services.audit import Kind, record

SKIP_PREFIXES = ("/static/", "/media/", "/sw.js", "/manifest", "/salud/", "/favicon", "/offline")
# Las entradas y salidas las registran las señales de autenticación (con más detalle).
SKIP_VIEWS = {"account_login", "account_logout", "account_signup"}
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class AuditMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        started = time.monotonic()
        response = self.get_response(request)
        if not request.path_info.startswith(SKIP_PREFIXES):  # path_info: sin /crecenta
            self._log(request, response, int((time.monotonic() - started) * 1000))
        return response

    def _log(self, request: HttpRequest, response: HttpResponse, duration_ms: int) -> None:
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return
        match = request.resolver_match
        view_name = match.view_name if match else ""
        if view_name in SKIP_VIEWS:
            return
        if request.method in WRITE_METHODS:
            kind = Kind.ACCION
        elif (
            request.method == "GET"
            and response.status_code == 200
            and not request.headers.get("HX-Request")
            and response.get("Content-Type", "").startswith("text/html")
        ):
            kind = Kind.VISITA
        else:
            return
        workspace = match.kwargs.get("ws") if match else None
        record(
            kind=kind,
            action=view_name or request.path,
            request=request,
            user=user,
            status=response.status_code,
            workspace_id=workspace if isinstance(workspace, uuid.UUID) else None,
            duration_ms=duration_ms,
            data={"htmx": True} if request.headers.get("HX-Request") else None,
        )
