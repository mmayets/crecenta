from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.urls import reverse

from apps.ledger.choices import TxStatus
from apps.ledger.models import Transaction
from apps.workspaces.models import Membership

from .models import Alert
from .services.evaluate import schedule_evaluation


@receiver(post_save, sender=Transaction, dispatch_uid="alertas_tras_movimiento")
def evaluate_after_transaction(sender, instance: Transaction, **kwargs) -> None:
    """Tras cada movimiento confirmado se reevalúan las alertas del espacio."""
    if instance.status == TxStatus.CONFIRMADO:
        workspace_id = instance.workspace_id
        transaction.on_commit(lambda: schedule_evaluation(workspace_id))


@receiver(post_save, sender=Alert, dispatch_uid="alertas_notificacion_push")
def push_new_alert(sender, instance: Alert, created: bool, **kwargs) -> None:
    """Las alertas urgentes y de atención nuevas llegan como notificación push a quienes llevan las
    finanzas del espacio (propietario y administradores)."""
    from apps.accounts.services.push import enabled

    if not created or instance.severity == Alert.Severity.INFO or not enabled():
        return
    alert_id = instance.pk
    transaction.on_commit(lambda: notify_alert(alert_id))


def notify_alert(alert_id) -> int:
    from apps.accounts.models import User
    from apps.accounts.services.push import PushMessage, send_to_users

    alert = Alert.objects.select_related("workspace").filter(pk=alert_id).first()
    if alert is None:
        return 0
    users = User.objects.filter(
        memberships__workspace=alert.workspace,
        memberships__role__in=[Membership.Role.OWNER, Membership.Role.ADMIN],
    )
    return send_to_users(
        users,
        PushMessage(
            title=f"{alert.workspace.name}: {alert.title}",
            body=alert.message,
            url=reverse("alerts:index", kwargs={"ws": alert.workspace_id}),
            tag=f"alerta-{alert.code}",
        ),
    )
