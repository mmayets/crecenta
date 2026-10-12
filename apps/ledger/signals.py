from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.workspaces.models import Workspace

from .services.recording import ensure_system_categories


@receiver(post_save, sender=Workspace, dispatch_uid="ledger_categorias_del_sistema")
def create_system_categories(sender, instance: Workspace, created: bool, **kwargs) -> None:
    if created:
        ensure_system_categories(instance)
