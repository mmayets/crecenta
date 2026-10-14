import json
from types import SimpleNamespace

import pytest
from django.urls import reverse

from apps.accounts.models import PushSubscription
from apps.accounts.services import push
from apps.accounts.tests.factories import UserFactory
from apps.alerts.models import Alert
from apps.backoffice.models import AuditEvent

pytestmark = pytest.mark.django_db
SUB = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/abc123",
    "keys": {"p256dh": "BOrAnDoMkEy", "auth": "aUtH"},
}


@pytest.fixture
def vapid(settings):
    settings.VAPID_PUBLIC_KEY = "BPub"
    settings.VAPID_PRIVATE_KEY = "priv"
    return settings


@pytest.fixture
def sent(monkeypatch):
    """Sustituye el envío real (pywebpush) y guarda lo que se habría enviado."""
    calls = []

    def fake_webpush(**kwargs):
        calls.append(kwargs)

    import pywebpush

    monkeypatch.setattr(pywebpush, "webpush", fake_webpush)
    return calls


def post_json(client, name, data):
    return client.post(
        reverse(f"accounts:{name}"), json.dumps(data), content_type="application/json"
    )


def test_suscribirse_probar_y_cancelar(client, user, vapid, sent):
    client.force_login(user)
    assert post_json(client, "push_subscribe", SUB).status_code == 200
    sub = PushSubscription.objects.get()
    assert (sub.user, sub.auth) == (user, "aUtH")
    response = post_json(client, "push_test", {})
    assert response.json() == {"ok": True, "enviadas": 1}
    payload = json.loads(sent[0]["data"])
    assert payload["title"] == "Crecenta" and payload["url"] == "/"
    assert sent[0]["subscription_info"]["endpoint"] == SUB["endpoint"]
    post_json(client, "push_unsubscribe", {"endpoint": SUB["endpoint"]})
    assert not PushSubscription.objects.exists()


def test_suscripcion_invalida(client, user, vapid):
    client.force_login(user)
    assert post_json(client, "push_subscribe", {"endpoint": "http://x"}).status_code == 400


def test_sin_claves_no_se_envia(client, user, settings, sent):
    settings.VAPID_PRIVATE_KEY = ""
    PushSubscription.objects.create(user=user, endpoint=SUB["endpoint"], p256dh="k", auth="a")
    assert push.send_to_user(user, push.PushMessage("t", "b")) == 0 and not sent


def test_suscripcion_vencida_se_borra(user, vapid, monkeypatch):
    from pywebpush import WebPushException

    def gone(**kwargs):
        raise WebPushException("gone", response=SimpleNamespace(status_code=410))

    import pywebpush

    monkeypatch.setattr(pywebpush, "webpush", gone)
    PushSubscription.objects.create(user=user, endpoint=SUB["endpoint"], p256dh="k", auth="a")
    assert push.send_to_user(user, push.PushMessage("t", "b")) == 0
    assert not PushSubscription.objects.exists()


def test_alerta_urgente_llega_como_push(
    user, personal_ws, vapid, sent, django_capture_on_commit_callbacks
):
    PushSubscription.objects.create(user=user, endpoint=SUB["endpoint"], p256dh="k", auth="a")
    with django_capture_on_commit_callbacks(execute=True):
        Alert.objects.create(workspace=personal_ws, code="x", dedupe_key="x",
                             severity=Alert.Severity.ALTA,
                             title="Te pasaste en ocio", message="Revisa tu plan.",
                             period_start=personal_ws.created_at.date())  # fmt: skip
        Alert.objects.create(workspace=personal_ws, code="y", dedupe_key="y",
                             severity=Alert.Severity.INFO,
                             title="Dato", message="Informativa.",
                             period_start=personal_ws.created_at.date())  # fmt: skip
    assert len(sent) == 1
    payload = json.loads(sent[0]["data"])
    assert payload["title"] == "Mis finanzas: Te pasaste en ocio"
    assert payload["url"] == reverse("alerts:index", kwargs={"ws": personal_ws.pk})


def test_el_panel_envia_mensajes_push(client, user, vapid, sent):
    staff = UserFactory(email="admin@example.com", is_staff=True)
    PushSubscription.objects.create(user=user, endpoint=SUB["endpoint"], p256dh="k", auth="a")
    client.force_login(staff)
    html = client.get(reverse("panel:notifications")).content.decode()
    assert 'data-testid="suscritas">1<' in html
    response = client.post(reverse("panel:notifications"),
                           {"destino": "todos", "titulo": "Novedad",
                            "mensaje": "Ya puedes escanear QR.", "enlace": "/"})  # fmt: skip
    assert response.status_code == 302 and len(sent) == 1
    assert AuditEvent.objects.get(action="panel:notificacion_enviada").data["enviadas"] == 1
    response = client.post(reverse("panel:notifications"),
                           {"destino": "todos", "titulo": "x", "mensaje": "y",
                            "enlace": "https://malo.example"})  # fmt: skip
    assert response.status_code == 400


def test_sophia_sugiere_activar_notificaciones(user, personal_ws, vapid):
    from datetime import date

    from apps.onboarding.services import guide

    keys = [s.key for s in guide.suggestions(personal_ws, user, "owner", date.today())]
    assert "push" in keys
    PushSubscription.objects.create(user=user, endpoint=SUB["endpoint"], p256dh="k", auth="a")
    keys = [s.key for s in guide.suggestions(personal_ws, user, "owner", date.today())]
    assert "push" not in keys
