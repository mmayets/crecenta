"""Notificaciones push (Web Push con claves VAPID).

`send_to_user` envía a todos los navegadores donde la persona las activó; las suscripciones que el
servicio push da por vencidas (404/410) se borran. Sin claves configuradas no se envía nada.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db.models import QuerySet
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import PushSubscription, User

logger = logging.getLogger(__name__)
TTL_SECONDS = 24 * 3600


@dataclass(frozen=True)
class PushMessage:
    title: str
    body: str
    url: str = ""  # vacío: el inicio de la app
    tag: str = ""

    def payload(self) -> str:
        return json.dumps(
            {
                "title": self.title[:80],
                "body": self.body[:240],
                "url": self.url or reverse("home"),
                "tag": self.tag,
                "icon": static("icons/icon-192.png"),
                "badge": static("icons/favicon-32.png"),
            },
            ensure_ascii=False,
        )


def enabled() -> bool:
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


def subscribe(user: User, data: dict[str, Any], user_agent: str = "") -> PushSubscription:
    """Guarda (o reasigna) la suscripción que entregó el navegador."""
    keys = data.get("keys") or {}
    endpoint = str(data.get("endpoint") or "")
    if not endpoint.startswith("https://") or not keys.get("p256dh") or not keys.get("auth"):
        raise ValueError("Suscripción incompleta.")
    subscription, _ = PushSubscription.objects.update_or_create(
        endpoint=endpoint[:600],
        defaults={
            "user": user,
            "p256dh": str(keys["p256dh"])[:200],
            "auth": str(keys["auth"])[:100],
            "user_agent": user_agent[:200],
        },
    )
    return subscription


def unsubscribe(user: User, endpoint: str) -> int:
    deleted, _ = PushSubscription.objects.filter(user=user, endpoint=endpoint).delete()
    return deleted


def _send(subscriptions: QuerySet[PushSubscription], message: PushMessage) -> int:
    if not enabled():
        return 0
    from pywebpush import WebPushException, webpush

    sent = 0
    for sub in subscriptions:
        try:
            webpush(
                subscription_info={"endpoint": sub.endpoint,
                                   "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                data=message.payload(),
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": settings.VAPID_SUBJECT},
                ttl=TTL_SECONDS,
            )  # fmt: skip
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):  # el navegador ya no la acepta
                sub.delete()
            else:
                logger.warning("No se pudo enviar la notificación push: %s", exc)
            continue
        except Exception:  # una suscripción defectuosa no debe frenar a las demás
            logger.exception("Error inesperado al enviar una notificación push")
            continue
        sub.last_sent_at = timezone.now()
        sub.save(update_fields=["last_sent_at"])
        sent += 1
    return sent


def send_to_user(user: User, message: PushMessage) -> int:
    return _send(PushSubscription.objects.filter(user=user, user__is_active=True), message)


def send_to_users(users, message: PushMessage) -> int:
    return _send(PushSubscription.objects.filter(user__in=users, user__is_active=True), message)


def send_to_everyone(message: PushMessage) -> int:
    return _send(PushSubscription.objects.filter(user__is_active=True), message)
