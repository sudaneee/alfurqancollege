from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib.auth.models import Group, Permission

from apps.academics.models import Department
from apps.core.forms import StyledForm, StyledFormMixin, StyledModelForm
from apps.core.models import CAPABILITIES

from .models import RoleProfile, StaffProfile, User


class LoginForm(StyledFormMixin, AuthenticationForm):
    username = forms.CharField(label="Username", widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "username"}))
    password = forms.CharField(label="Password", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))


class StyledPasswordChangeForm(StyledFormMixin, PasswordChangeForm):
    pass


class ApplicantSignupForm(StyledForm):
    first_name = forms.CharField(max_length=100)
    last_name = forms.CharField(label="Surname", max_length=100)
    email = forms.EmailField(help_text="You will sign in with this e-mail address.")
    phone = forms.CharField(max_length=30)
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
                                help_text="At least 8 characters; not entirely numeric.")
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists() or User.objects.filter(username__iexact=email).exists():
            raise forms.ValidationError("An account with this e-mail already exists. Sign in instead.")
        return email

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "The passwords do not match.")
        if p1:
            temp = User(username=data.get("email", ""), first_name=data.get("first_name", ""), last_name=data.get("last_name", ""))
            try:
                password_validation.validate_password(p1, temp)
            except forms.ValidationError as exc:
                self.add_error("password1", exc)
        return data


class StaffUserForm(StyledModelForm):
    staff_id = forms.CharField(max_length=40, label="Staff ID")
    department = forms.ModelChoiceField(queryset=Department.objects.all(), required=False)
    designation = forms.CharField(max_length=120, required=False)
    qualification = forms.CharField(max_length=200, required=False)
    groups = forms.ModelMultipleChoiceField(queryset=Group.objects.order_by("name"), required=False, label="Roles",
                                            widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = User
        fields = ["first_name", "other_names", "last_name", "email", "phone", "username", "is_active"]
        help_texts = {"username": "Used to sign in (staff can also sign in with e-mail or staff ID)."}

    def __init__(self, *args, can_assign_roles=True, **kwargs):
        super().__init__(*args, **kwargs)
        prof = getattr(self.instance, "staff_profile", None) if self.instance.pk else None
        if prof:
            self.fields["staff_id"].initial = prof.staff_id
            self.fields["department"].initial = prof.department_id
            self.fields["designation"].initial = prof.designation
            self.fields["qualification"].initial = prof.qualification
        if self.instance.pk:
            self.fields["groups"].initial = self.instance.groups.all()
        if not can_assign_roles:
            del self.fields["groups"]
        self.fields["email"].required = True

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Another account uses this e-mail address.")
        return email

    def clean_staff_id(self):
        sid = self.cleaned_data["staff_id"].strip().upper()
        qs = StaffProfile.objects.filter(staff_id__iexact=sid)
        if self.instance.pk:
            qs = qs.exclude(user=self.instance)
        if qs.exists():
            raise forms.ValidationError("This staff ID is already in use.")
        return sid


class RoleForm(StyledModelForm):
    description = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)
    dashboard = forms.ChoiceField(choices=[("", "—")] + RoleProfile._meta.get_field("dashboard").choices, required=False)

    class Meta:
        model = Group
        fields = ["name"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        prof = getattr(self.instance, "profile", None) if self.instance.pk else None
        if prof:
            self.fields["description"].initial = prof.description
            self.fields["dashboard"].initial = prof.dashboard
        current = set(self.instance.permissions.values_list("codename", flat=True)) if self.instance.pk else set()
        self.capability_groups = {}
        for code, group, label in CAPABILITIES:
            self.capability_groups.setdefault(group, []).append({"code": code, "label": label, "checked": code in current})

    def save_permissions(self, codes):
        perms = Permission.objects.filter(content_type__app_label="core", codename__in=codes)
        self.instance.permissions.set(perms)


class AdminPasswordResetForm(StyledForm):
    password = forms.CharField(required=False, widget=forms.PasswordInput, help_text="Leave empty to generate a temporary password.")
    must_change = forms.BooleanField(required=False, initial=True, label="Require password change at next sign-in")
