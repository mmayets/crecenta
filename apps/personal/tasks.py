from celery import shared_task
from django.utils import timezone

from apps.personal.services.auto_record import record_due_all


@shared_task(name="personal.auto_record_all", ignore_result=True)
def auto_record_all_task() -> int:
    """Cada mañana (celery beat): cobros y pagos fijos del día en los espacios que lo activaron."""
    return record_due_all(timezone.localdate())
