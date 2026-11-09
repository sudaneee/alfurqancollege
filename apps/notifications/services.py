"""Notification service.

`notify()` renders a database-managed template and delivers it on each
enabled channel. In-app delivery is immediate; e-mail goes through Django's
mail backend; SMS goes through a pluggable backend (`SMS_BACKEND` setting) so a
Nigerian SMS provider can be added without touching callers.
"""
import logging
from importlib import import_module

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from .models import Notification, NotificationTemplate, OutboundMessage

logger = logging.getLogger("apps.notifications")


class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def render(text, context):
    try:
        return text.format_map(_SafeDict(context))
    except (ValueError, IndexError):
        return text


class LoggingSMSBackend:
    """Default SMS backend: records the message without sending (configure a provider in production)."""

    def send(self, phone, message):
        logger.info("SMS to %s: %s", phone, message)
        return False, "No SMS provider configured"


def _sms_backend():
    path = getattr(settings, "SMS_BACKEND", "")
    if not path:
        return LoggingSMSBackend()
    module, _, cls = path.rpartition(".")
    return getattr(import_module(module), cls)()


def notify(user, key, context=None, link="", fallback_title="", fallback_body=""):
    if user is None:
        return None
    context = dict(context or {})
    context.setdefault("name", user.get_full_name() or user.username)
    context.setdefault("college", "Alfurqan College of Health Sciences and Technology")
    tpl = NotificationTemplate.objects.filter(key=key, is_active=True).first()
    if tpl is None and not fallback_title:
        return None
    title = render(tpl.subject if tpl else fallback_title, context)
    body = render(tpl.body if tpl else fallback_body, context)
    note = None
    if tpl is None or tpl.send_in_app:
        note = Notification.objects.create(recipient=user, title=title[:200], body=body, link=link, category=key)
    if tpl and tpl.send_email and user.email:
        msg = OutboundMessage.objects.create(channel="email", recipient=user, to=user.email, subject=title, body=body)
        try:
            send_mail(title, body, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
            msg.status, msg.sent_at = "sent", timezone.now()
        except Exception as exc:  # delivery problems must never break the business action
            msg.status, msg.error = "failed", str(exc)[:255]
        msg.save()
    if tpl and tpl.send_sms and user.phone:
        msg = OutboundMessage.objects.create(channel="sms", recipient=user, to=user.phone, body=body)
        ok, info = _sms_backend().send(user.phone, body)
        msg.status = "sent" if ok else "not_sent"
        msg.error = "" if ok else (info or "")[:255]
        msg.sent_at = timezone.now() if ok else None
        msg.save()
    return note


def broadcast(users, title, body, link="", category="announcement"):
    Notification.objects.bulk_create(
        [Notification(recipient=u, title=title[:200], body=body, link=link, category=category) for u in users]
    )
