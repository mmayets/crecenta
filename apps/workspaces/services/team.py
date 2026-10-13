"""Equipo de un negocio: invitar por enlace, aceptar, cambiar rol y quitar (docs/fase4.md §2).

- Solo los espacios de negocio se comparten; el personal nunca.
- El código del enlace se guarda como hash (SHA-256): si se filtra la base, los enlaces no sirven.
- El enlace es de un solo uso, vence en 7 días y solo lo acepta quien inicia sesión con el correo
  invitado.
"""

from __future__ import annotations

import datetime
import hashlib
import secrets

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.workspaces.models import Invitation, Membership, Workspace

INVITATION_DAYS = 7
INVITABLE_ROLES = (Membership.Role.ADMIN, Membership.Role.VENDEDOR)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _require_owner(workspace: Workspace, user: User) -> None:
    is_owner = Membership.objects.filter(
        workspace=workspace, user=user, role=Membership.Role.OWNER
    ).exists()
    if not is_owner:
        raise ValidationError("Solo el propietario puede administrar el equipo.")


def create_invitation(
    workspace: Workspace, by: User, email: str, role: str
) -> tuple[Invitation, str]:
    """Crea la invitación y devuelve también el código (solo se puede mostrar ahora)."""
    if not workspace.is_business:
        raise ValidationError("Tus finanzas personales no se comparten.")
    _require_owner(workspace, by)
    email = email.strip().lower()
    if role not in INVITABLE_ROLES:
        raise ValidationError({"role": "Elige administrador o vendedor."})
    if Membership.objects.filter(workspace=workspace, user__email__iexact=email).exists():
        raise ValidationError({"email": "Esa persona ya es parte de este negocio."})
    token = secrets.token_urlsafe(32)
    with transaction.atomic():
        # Una invitación vigente por correo: la anterior queda anulada.
        Invitation.objects.filter(
            workspace=workspace, email__iexact=email, accepted_at=None, revoked_at=None
        ).update(revoked_at=timezone.now())
        invitation = Invitation.objects.create(
            workspace=workspace,
            email=email,
            role=role,
            token_hash=_hash(token),
            expires_at=timezone.now() + datetime.timedelta(days=INVITATION_DAYS),
            created_by=by,
        )
    return invitation, token


def find_invitation(token: str) -> Invitation | None:
    invitation: Invitation | None = (
        Invitation.objects.select_related("workspace").filter(token_hash=_hash(token)).first()
    )
    return invitation


def invitation_problem(invitation: Invitation | None, user: User | None = None) -> str | None:
    """Por qué no se puede aceptar (None si se puede)."""
    if invitation is None:
        return "Este enlace no es válido."
    if invitation.revoked_at:
        return "Esta invitación fue anulada por el propietario."
    if invitation.accepted_at:
        return "Esta invitación ya se usó."
    if invitation.expires_at < timezone.now():
        return "Esta invitación venció. Pide un enlace nuevo."
    if user is not None and user.email.lower() != invitation.email.lower():
        return (
            f"Esta invitación es para {invitation.email}. Inicia sesión con ese correo para "
            "aceptarla."
        )
    return None


@transaction.atomic
def accept_invitation(user: User, token: str) -> Membership:
    invitation = find_invitation(token)
    if invitation is not None:
        invitation = Invitation.objects.select_for_update().get(pk=invitation.pk)
    problem = invitation_problem(invitation, user)
    if problem:
        raise ValidationError(problem)
    assert invitation is not None
    membership, _ = Membership.objects.get_or_create(
        user=user, workspace=invitation.workspace, defaults={"role": invitation.role}
    )
    invitation.accepted_at = timezone.now()
    invitation.accepted_by = user
    invitation.save(update_fields=["accepted_at", "accepted_by", "updated_at"])
    return membership


def revoke_invitation(workspace: Workspace, by: User, invitation: Invitation) -> None:
    _require_owner(workspace, by)
    if invitation.workspace_id != workspace.pk:
        raise ValidationError("No pertenece a este negocio.")
    invitation.revoked_at = timezone.now()
    invitation.save(update_fields=["revoked_at", "updated_at"])


def _editable(workspace: Workspace, by: User, membership: Membership) -> None:
    _require_owner(workspace, by)
    if membership.workspace_id != workspace.pk:
        raise ValidationError("No pertenece a este negocio.")
    if membership.role == Membership.Role.OWNER:
        raise ValidationError("El rol del propietario no se cambia.")


def change_role(workspace: Workspace, by: User, membership: Membership, role: str) -> Membership:
    _editable(workspace, by, membership)
    if role not in INVITABLE_ROLES:
        raise ValidationError({"role": "Elige administrador o vendedor."})
    membership.role = role
    membership.save(update_fields=["role", "updated_at"])
    return membership


def remove_member(workspace: Workspace, by: User, membership: Membership) -> None:
    """Quita el acceso; lo que esa persona registró se queda (created_by apunta a ella)."""
    _editable(workspace, by, membership)
    membership.delete()
