"""Role/permission helpers used by every staff-facing view."""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse


def perm(code):
    return code if "." in code else f"core.{code}"


def has_perm(user, code):
    return bool(user and user.is_authenticated and user.is_active and user.has_perm(perm(code)))


def has_any(user, *codes):
    return any(has_perm(user, c) for c in codes)


def is_staff_member(user):
    return bool(user and user.is_authenticated and (user.is_superuser or user.user_type == "staff"))


def staff_required(*codes):
    """Require a staff account and (if codes are given) at least one of the permissions."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                return redirect_to_login(request.get_full_path(), reverse("accounts:staff_login"))
            if not is_staff_member(user):
                raise PermissionDenied("This area is restricted to College staff.")
            if codes and not has_any(user, *codes):
                raise PermissionDenied("You do not have permission to perform this action.")
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


def require(request, *codes):
    """Inline permission check for views that need finer-grained checks."""
    if not has_any(request.user, *codes):
        raise PermissionDenied("You do not have permission to perform this action.")


def student_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return redirect_to_login(request.get_full_path(), reverse("accounts:student_login"))
        student = getattr(user, "student", None)
        if student is None:
            messages.error(request, "Your account is not linked to a student record.")
            return redirect("accounts:route")
        request.student = student
        return view(request, *args, **kwargs)

    return wrapper


def applicant_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return redirect_to_login(request.get_full_path(), reverse("accounts:applicant_login"))
        if user.user_type not in ("applicant", "student"):
            raise PermissionDenied("The application portal is for applicants.")
        return view(request, *args, **kwargs)

    return wrapper
