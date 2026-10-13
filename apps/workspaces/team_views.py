"""Pantallas del equipo de un negocio y aceptación de invitaciones."""

from __future__ import annotations

from typing import Any

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from .mixins import workspace_required
from .models import Invitation, Membership, Workspace
from .permissions import PROPIETARIO
from .services.team import (
    INVITABLE_ROLES,
    accept_invitation,
    change_role,
    create_invitation,
    find_invitation,
    invitation_problem,
    remove_member,
    revoke_invitation,
)

ROLE_CHOICES = [(r.value, r.label) for r in INVITABLE_ROLES]
team_owner = workspace_required(kind="business", perm=PROPIETARIO)


class InviteForm(forms.Form):
    email = forms.EmailField(label="Correo de la persona")
    role = forms.ChoiceField(
        label="Rol",
        choices=ROLE_CHOICES,
        initial=Membership.Role.VENDEDOR,
        widget=forms.RadioSelect,
        help_text="Vendedor: registra ventas y cobros, no ve costos ni ganancias. "
        "Administrador: todo menos retiros y equipo.",
    )


def _get(model: Any, workspace: Workspace, pk: Any) -> Any:
    try:
        return model.objects.get(pk=pk, workspace=workspace)
    except (model.DoesNotExist, ValidationError, ValueError) as exc:
        raise Http404 from exc


@team_owner
@require_http_methods(["GET", "POST"])
def team(request: HttpRequest, workspace: Workspace) -> HttpResponse:
    form = InviteForm(request.POST or None)
    link = None
    if request.method == "POST" and form.is_valid():
        try:
            _, token = create_invitation(
                workspace, request.user, form.cleaned_data["email"], form.cleaned_data["role"]
            )  # type: ignore[arg-type]
        except ValidationError as exc:
            for message in exc.messages:
                form.add_error(None, message)
        else:
            link = request.build_absolute_uri(f"/invitacion/{token}/")
            messages.success(
                request, "Invitación creada. Comparte el enlace: solo se muestra ahora."
            )
            form = InviteForm()
    return render(
        request,
        "workspaces/team.html",
        {
            "workspace": workspace,
            "form": form,
            "link": link,
            "members": Membership.objects.filter(workspace=workspace).select_related("user"),
            "pending": Invitation.objects.filter(
                workspace=workspace, accepted_at=None, revoked_at=None
            ),
            "roles": ROLE_CHOICES,
        },
        status=400 if request.method == "POST" and link is None else 200,
    )


@team_owner
@require_POST
def member_role(request: HttpRequest, workspace: Workspace, member_id: Any) -> HttpResponse:
    membership = _get(Membership, workspace, member_id)
    try:
        change_role(workspace, request.user, membership, request.POST.get("role", ""))  # type: ignore[arg-type]
        messages.success(request, "Rol actualizado.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("espacio:team", ws=workspace.pk)


@team_owner
@require_POST
def member_remove(request: HttpRequest, workspace: Workspace, member_id: Any) -> HttpResponse:
    membership = _get(Membership, workspace, member_id)
    try:
        remove_member(workspace, request.user, membership)  # type: ignore[arg-type]
        messages.info(request, "La persona ya no tiene acceso. Lo que registró se conserva.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("espacio:team", ws=workspace.pk)


@team_owner
@require_POST
def invitation_revoke(
    request: HttpRequest, workspace: Workspace, invitation_id: Any
) -> HttpResponse:
    invitation = _get(Invitation, workspace, invitation_id)
    revoke_invitation(workspace, request.user, invitation)  # type: ignore[arg-type]
    messages.info(request, "Invitación anulada: el enlace ya no sirve.")
    return redirect("espacio:team", ws=workspace.pk)


@login_required
@require_http_methods(["GET", "POST"])
def accept(request: HttpRequest, token: str) -> HttpResponse:
    invitation = find_invitation(token)
    problem = invitation_problem(invitation, request.user)  # type: ignore[arg-type]
    if request.method == "POST" and not problem:
        try:
            membership = accept_invitation(request.user, token)  # type: ignore[arg-type]
        except ValidationError as exc:
            problem = " ".join(exc.messages)
        else:
            role = membership.get_role_display().lower()
            messages.success(request, f"Ya eres parte de {membership.workspace.name} ({role}).")
            return redirect("espacio:dashboard", ws=membership.workspace_id)
    return render(
        request,
        "workspaces/invitation.html",
        {"invitation": invitation, "problem": problem},
        status=400 if problem else 200,
    )
