import contextvars

from django.shortcuts import redirect
from django.urls import reverse

_current_request = contextvars.ContextVar("current_request", default=None)


def get_current_request():
    return _current_request.get()


def client_ip(request):
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


class AuditContextMiddleware:
    """Makes the current request available to the audit service and enforces
    forced password changes (e.g. after an administrator reset)."""

    EXEMPT_PREFIXES = ("/static/", "/media/", "/accounts/password/", "/accounts/logout/", "/payments/webhook/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _current_request.set(request)
        try:
            user = getattr(request, "user", None)
            if (
                user is not None
                and user.is_authenticated
                and getattr(user, "must_change_password", False)
                and not request.path.startswith(self.EXEMPT_PREFIXES)
            ):
                return redirect(reverse("accounts:password_change"))
            return self.get_response(request)
        finally:
            _current_request.reset(token)
