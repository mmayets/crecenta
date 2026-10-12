from celery import shared_task

from apps.receipts.services.ocr import read_receipt


@shared_task(name="receipts.read_receipt", ignore_result=True)
def read_receipt_task(receipt_id: str) -> None:
    read_receipt(receipt_id)
