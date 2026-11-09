from django.conf import settings
from django.db import models


class NotificationTemplate(models.Model):
    key = models.SlugField(max_length=60, unique=True, help_text="System key used by the platform (do not change)")
    name = models.CharField(max_length=120)
    subject = models.CharField(max_length=200, help_text="Supports placeholders such as {name}")
    body = models.TextField(help_text="Supports placeholders such as {name}, {programme}, {amount}")
    placeholders = models.CharField(max_length=255, blank=True, help_text="Available placeholders (for reference)")
    send_in_app = models.BooleanField(default=True)
    send_email = models.BooleanField(default=False)
    send_sms = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Notification(models.Model):
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    link = models.CharField(max_length=300, blank=True)
    category = models.CharField(max_length=40, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class OutboundMessage(models.Model):
    """Queue/log of e-mail and SMS deliveries (for future channels & auditing)."""

    CHANNEL_CHOICES = [("email", "E-mail"), ("sms", "SMS")]
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES)
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    to = models.CharField(max_length=200)
    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField()
    status = models.CharField(max_length=20, default="queued")
    error = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
