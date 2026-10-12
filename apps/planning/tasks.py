from celery import shared_task

from apps.planning.services.generate import narrate_plan


@shared_task(name="planning.narrate_plan", ignore_result=True)
def narrate_plan_task(plan_id: str) -> None:
    narrate_plan(plan_id)
