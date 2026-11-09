from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.core import audit
from apps.core.permissions import has_perm, staff_required
from apps.students.services import temporary_password

from .forms import AdminPasswordResetForm, ApplicantSignupForm, LoginForm, RoleForm, StyledPasswordChangeForm, StaffUserForm
from .models import RoleProfile, StaffProfile, User

PORTALS = {
    "applicant": {"title": "Application Portal", "lead": "Apply for admission, upload documents, pay fees and track your application.",
                  "types": ("applicant", "student"), "home": "admissions:portal_dashboard", "label": "E-mail address"},
    "student": {"title": "Student Portal", "lead": "Register courses, check results, pay fees and download documents.",
                "types": ("student",), "home": "students:portal_dashboard", "label": "Matric number or e-mail"},
    "staff": {"title": "Staff Portal", "lead": "Administration, admissions, academics, results and bursary.",
              "types": ("staff",), "home": "core:dashboard", "label": "Staff ID, username or e-mail"},
}


def _safe_next(request, fallback):
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return nxt
    return fallback


def portal_login(request, portal):
    cfg = PORTALS[portal]
    if request.user.is_authenticated and (request.user.user_type in cfg["types"] or (portal == "staff" and request.user.is_superuser)):
        return redirect(cfg["home"])
    form = LoginForm(request, data=request.POST or None)
    form.fields["username"].label = cfg["label"]
    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        allowed = user.user_type in cfg["types"] or (portal == "staff" and user.is_superuser)
        if not allowed:
            right = next((k for k, v in PORTALS.items() if user.user_type in v["types"]), "applicant")
            messages.error(request, f"This account belongs to the {PORTALS[right]['title']}. Please sign in there.")
            return redirect(f"accounts:{right}_login")
        login(request, user)
        audit.log(user, "login", user, module="accounts", note=portal)
        return redirect(_safe_next(request, user.portal_home if portal != "applicant" else cfg["home"]))
    return render(request, "accounts/login.html", {"form": form, "portal": portal, "cfg": cfg})


def applicant_login(request):
    return portal_login(request, "applicant")


def student_login(request):
    return portal_login(request, "student")


def staff_login(request):
    return portal_login(request, "staff")


def login_chooser(request):
    if request.user.is_authenticated:
        return redirect("accounts:route")
    return redirect("accounts:student_login")


@login_required
def route(request):
    return redirect(request.user.portal_home)


@require_POST
def logout_view(request):
    if request.user.is_authenticated:
        audit.log(request.user, "logout", request.user, module="accounts")
    logout(request)
    messages.info(request, "You have been signed out.")
    return redirect("website:home")


def applicant_signup(request):
    if request.user.is_authenticated:
        return redirect("accounts:route")
    form = ApplicantSignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        user = User(username=d["email"], email=d["email"], first_name=d["first_name"], last_name=d["last_name"],
                    phone=d["phone"], user_type=User.APPLICANT)
        user.set_password(d["password1"])
        user.save()
        audit.log(user, "applicant_registered", user, module="accounts")
        login(request, user, backend="apps.accounts.backends.EmailOrUsernameBackend")
        messages.success(request, "Your account has been created. Complete your application form below.")
        return redirect("admissions:portal_dashboard")
    return render(request, "accounts/signup.html", {"form": form, "cfg": PORTALS["applicant"], "portal": "applicant"})


@login_required
def password_change(request):
    form = StyledPasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        user.must_change_password = False
        user.save(update_fields=["must_change_password"])
        update_session_auth_hash(request, user)
        audit.log(user, "password_changed", user, module="accounts")
        messages.success(request, "Your password has been changed.")
        return redirect(user.portal_home)
    base = "staff/base.html" if request.user.user_type == "staff" or request.user.is_superuser else (
        "students/portal/base.html" if request.user.user_type == "student" else "admissions/portal/base.html")
    return render(request, "accounts/password_change.html", {"form": form, "base_template": base})


# ---------------------------------------------------------------------------
# User management (Super Admin / authorised administrators)
# ---------------------------------------------------------------------------
@staff_required("manage_users")
def user_list(request):
    qs = User.objects.prefetch_related("groups").select_related("staff_profile__department")
    utype = request.GET.get("type", "staff")
    if utype in ("staff", "student", "applicant"):
        qs = qs.filter(user_type=utype)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)
                       | Q(email__icontains=q) | Q(staff_profile__staff_id__icontains=q) | Q(student__matric_number__icontains=q))
    role = request.GET.get("role")
    if role:
        qs = qs.filter(groups__id=role)
    status = request.GET.get("status")
    if status == "inactive":
        qs = qs.filter(is_active=False)
    elif status == "active":
        qs = qs.filter(is_active=True)
    page = Paginator(qs.order_by("first_name", "last_name"), 30).get_page(request.GET.get("page"))
    return render(request, "accounts/user_list.html", {"page": page, "q": q, "utype": utype, "roles": Group.objects.order_by("name"),
                                                       "role": role, "status": status})


def _save_staff(form, actor, user=None):
    with transaction.atomic():
        before = audit.snapshot(form.instance) if form.instance.pk else {}
        before_roles = sorted(form.instance.groups.values_list("name", flat=True)) if form.instance.pk else []
        u = form.save(commit=False)
        u.user_type = User.STAFF
        temp = None
        if not u.pk:
            temp = temporary_password()
            u.set_password(temp)
            u.must_change_password = True
        u.save()
        if "groups" in form.cleaned_data:
            if not has_perm(actor, "manage_roles") and not actor.is_superuser:
                raise PermissionDenied("You cannot assign roles.")
            if not actor.is_super_admin and any(g.name == "Super Administrator" for g in form.cleaned_data["groups"]):
                if "Super Administrator" not in before_roles:
                    raise PermissionDenied("Only a Super Administrator can grant the Super Administrator role.")
            u.groups.set(form.cleaned_data["groups"])
        StaffProfile.objects.update_or_create(user=u, defaults={
            "staff_id": form.cleaned_data["staff_id"], "department": form.cleaned_data.get("department"),
            "designation": form.cleaned_data.get("designation", ""), "qualification": form.cleaned_data.get("qualification", "")})
        changes = audit.diff(before, audit.snapshot(u))
        after_roles = sorted(u.groups.values_list("name", flat=True))
        if after_roles != before_roles:
            changes["roles"] = [before_roles, after_roles]
        audit.log(actor, "user_updated" if before else "user_created", u, module="accounts", changes=changes)
    return u, temp


@staff_required("manage_users")
def user_create(request):
    form = StaffUserForm(request.POST or None, can_assign_roles=has_perm(request.user, "manage_roles"))
    if request.method == "POST" and form.is_valid():
        u, temp = _save_staff(form, request.user)
        messages.success(request, f"Staff account created for {u}. Temporary password: {temp} — share it securely; "
                                  "they must change it at first sign-in.")
        return redirect("accounts:user_detail", u.pk)
    return render(request, "accounts/user_form.html", {"form": form})


@staff_required("manage_users")
def user_edit(request, pk):
    user = get_object_or_404(User, pk=pk, user_type=User.STAFF)
    if user.is_superuser and not request.user.is_superuser:
        raise PermissionDenied("Only a Super Administrator can edit this account.")
    form = StaffUserForm(request.POST or None, instance=user, can_assign_roles=has_perm(request.user, "manage_roles"))
    if request.method == "POST" and form.is_valid():
        _save_staff(form, request.user)
        messages.success(request, "Account updated.")
        return redirect("accounts:user_detail", user.pk)
    return render(request, "accounts/user_form.html", {"form": form, "object": user})


@staff_required("manage_users")
def user_detail(request, pk):
    user = get_object_or_404(User.objects.prefetch_related("groups"), pk=pk)
    from apps.core.models import AuditLog
    activity = AuditLog.objects.filter(Q(actor=user) | Q(on_behalf_of=user))[:15]
    perms = sorted(p.split(".", 1)[1] for p in user.get_all_permissions() if p.startswith("core."))
    return render(request, "accounts/user_detail.html", {"obj": user, "activity": activity, "perms": perms,
                                                         "reset_form": AdminPasswordResetForm()})


@staff_required("manage_users")
@require_POST
def user_toggle_active(request, pk):
    user = get_object_or_404(User, pk=pk)
    if user == request.user:
        messages.error(request, "You cannot deactivate your own account.")
        return redirect("accounts:user_detail", pk)
    if user.is_superuser and not request.user.is_superuser:
        raise PermissionDenied("Only a Super Administrator can change this account.")
    user.is_active = not user.is_active
    user.save(update_fields=["is_active"])
    audit.log(request.user, "user_activated" if user.is_active else "user_deactivated", user, module="accounts")
    messages.success(request, f"{user} has been {'activated' if user.is_active else 'deactivated'}.")
    return redirect("accounts:user_detail", pk)


@staff_required("manage_users")
@require_POST
def user_reset_password(request, pk):
    user = get_object_or_404(User, pk=pk)
    if user.is_superuser and not request.user.is_superuser:
        raise PermissionDenied("Only a Super Administrator can reset this password.")
    form = AdminPasswordResetForm(request.POST)
    if form.is_valid():
        pwd = form.cleaned_data["password"] or temporary_password()
        user.set_password(pwd)
        user.must_change_password = form.cleaned_data["must_change"]
        user.save()
        audit.log(request.user, "password_reset", user, module="accounts", on_behalf_of=user)
        messages.success(request, f"Password for {user} reset. New password: {pwd}")
    return redirect(_safe_next(request, f"/staff/users/{pk}/"))


# ---------------------------------------------------------------------------
# Roles & permissions
# ---------------------------------------------------------------------------
@staff_required("manage_roles")
def role_list(request):
    roles = Group.objects.order_by("name").prefetch_related("permissions", "user_set")
    return render(request, "accounts/role_list.html", {"roles": roles})


@staff_required("manage_roles")
def role_form(request, pk=None):
    group = get_object_or_404(Group, pk=pk) if pk else None
    if group and group.name == "Super Administrator" and not request.user.is_super_admin:
        raise PermissionDenied("Only a Super Administrator can edit this role.")
    form = RoleForm(request.POST or None, instance=group)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            before = sorted(group.permissions.values_list("codename", flat=True)) if group else []
            g = form.save()
            codes = request.POST.getlist("caps")
            form.instance = g
            form.save_permissions(codes)
            RoleProfile.objects.update_or_create(group=g, defaults={"description": form.cleaned_data["description"],
                                                                    "dashboard": form.cleaned_data["dashboard"]})
            audit.log(request.user, "role_updated" if group else "role_created", g, module="accounts",
                      changes={"permissions": [before, sorted(codes)]})
        messages.success(request, f"Role “{g.name}” saved.")
        return redirect("accounts:role_list")
    return render(request, "accounts/role_form.html", {"form": form, "object": group})


@staff_required("manage_roles")
@require_POST
def role_delete(request, pk):
    group = get_object_or_404(Group, pk=pk)
    prof = getattr(group, "profile", None)
    if prof and prof.is_system:
        messages.error(request, "Built-in roles cannot be deleted. Remove their permissions instead.")
    elif group.user_set.exists():
        messages.error(request, "Remove all users from this role before deleting it.")
    else:
        audit.log(request.user, "role_deleted", None, module="accounts", object_repr=group.name)
        group.delete()
        messages.success(request, "Role deleted.")
    return redirect("accounts:role_list")
