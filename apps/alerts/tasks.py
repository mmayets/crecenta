from celery import shared_task

from apps.alerts.services.evaluate import evaluate_workspace
from apps.workspaces.models import Workspace


@shared_task(name="alerts.evaluate_workspace", ignore_result=True)
def evaluate_workspace_task(workspace_id: str) -> None:
    workspace = Workspace.objects.filter(pk=workspace_id).first()
    if workspace is not None:
        evaluate_workspace(workspace)


@shared_task(name="alerts.evaluate_all", ignore_result=True)
def evaluate_all_task() -> int:
    """Evaluación diaria (celery beat) de todos los espacios, personales y de negocio."""
    ids = list(Workspace.objects.values_list("id", flat=True))
    for workspace_id in ids:
        evaluate_workspace_task.delay(str(workspace_id))
    return len(ids)
