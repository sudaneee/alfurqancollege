from decimal import Decimal, InvalidOperation

from django import template
from django.utils.html import format_html

from apps.core.permissions import has_any

register = template.Library()


@register.filter
def naira(value):
    try:
        value = Decimal(value or 0)
    except (InvalidOperation, TypeError, ValueError):
        return value
    return "₦{:,.2f}".format(value)


@register.simple_tag(takes_context=True)
def can(context, *codes):
    return has_any(context["request"].user, *codes)


@register.filter
def getattr_(obj, name):
    value = obj
    for part in str(name).split("__"):
        if value is None:
            return ""
        if isinstance(value, dict):
            value = value.get(part)
            continue
        display = getattr(value, f"get_{part}_display", None)
        value = display() if callable(display) else getattr(value, part, "")
        if callable(value) and not hasattr(value, "all"):
            value = value()
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    return "" if value is None else value


@register.filter
def get_item(d, key):
    if isinstance(d, dict):
        return d.get(key)
    return None


STATUS_TONES = {
    "success": ("published", "paid", "approved", "successful", "active", "admitted", "accepted", "verified",
                "applied", "graduated", "open", "yes", "pass", "passed"),
    "warning": ("submitted", "pending", "part_paid", "under_review", "hod_approved", "preview", "unpaid",
                "awaiting_payment", "partly_paid"),
    "info": ("draft", "in_progress", "returned_for_correction"),
    "danger": ("rejected", "failed", "not_admitted", "declined", "suspended", "withdrawn", "cancelled", "returned",
               "reversed", "closed", "no", "fail", "outstanding"),
}


@register.simple_tag
def status_badge(value, label=None):
    key = str(value or "").lower().replace(" ", "_")
    tone = "neutral"
    for t, keys in STATUS_TONES.items():
        if key in keys:
            tone = t
            break
    text = label or str(value or "—").replace("_", " ").title()
    return format_html('<span class="badge-status badge-{}">{}</span>', tone, text)


@register.simple_tag(takes_context=True)
def query_replace(context, **kwargs):
    q = context["request"].GET.copy()
    for k, v in kwargs.items():
        q[k] = v
    return q.urlencode()


@register.filter
def initials(user):
    name = (user.get_full_name() or user.get_username() or "?").split()
    return "".join(p[0] for p in name[:2]).upper()


@register.filter
def split_lines(text):
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


@register.filter
def nice(value):
    """'payment_recorded' -> 'payment recorded'."""
    return str(value or "").replace("_", " ")
