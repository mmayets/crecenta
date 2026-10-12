from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.ledger.choices import TxStatus
from apps.ledger.models import Transaction

from .services.evaluate import schedule_evaluation


@receiver(post_save, sender=Transaction, dispatch_uid="alertas_tras_movimiento")
def evaluate_after_transaction(sender, instance: Transaction, **kwargs) -> None:
    """Tras cada movimiento confirmado se reevalúan las alertas del espacio."""
    if instance.status == TxStatus.CONFIRMADO:
        workspace_id = instance.workspace_id
        transaction.on_commit(lambda: schedule_evaluation(workspace_id))
