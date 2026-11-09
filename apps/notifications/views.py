from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.academics.models import Programme
from apps.accounts.models import User
from apps.core import audit
from apps.core.crud import Crud
from apps.core.forms import StyledForm, StyledModelForm
from apps.core.permissions import staff_required

from .models import Notification, NotificationTemplate
from .services import broadcast as do_broadcast


class TemplateForm(StyledModelForm):
    class Meta:
        model = NotificationTemplate
        fields = ["name", "key", "subject", "body", "placeholders", "send_in_app", "send_email", "send_sms", "is_active"]


TEMPLATE_CRUD = Crud("template", NotificationTemplate, TemplateForm, ("manage_notifications",), "Notification templates",
                     "Template", section="System settings", can_delete=False,
                     description="Wording of automatic messages. Use placeholders shown on each template, e.g. {name}.",
                     list_display=[("Template", "name"), ("Key", "key"), ("In-app", "send_in_app"), ("E-mail", "send_email"),
                                   ("SMS", "send_sms"), ("Active", "is_active")])


def _base(user):
    if user.user_type == "staff" or user.is_superuser:
        return "staff/base.html"
    if user.user_type == "student":
        return "students/portal/base.html"
    return "admissions/portal/base.html"


@login_required
def notification_list(request):
    qs = request.user.notifications.all()
    if request.method == "POST":
        qs.filter(is_read=False).update(is_read=True)
        messages.success(request, "All notifications marked as read.")
        return redirect("notifications:list")
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "notifications/list.html", {"page": page, "base_template": _base(request.user)})


@login_required
def open_notification(request, pk):
    n = get_object_or_404(Notification, pk=pk, recipient=request.user)
    if not n.is_read:
        n.is_read = True
        n.save(update_fields=["is_read"])
    if n.link and url_has_allowed_host_and_scheme(n.link, allowed_hosts={request.get_host()}):
        return redirect(n.link)
    return redirect("notifications:list")


class BroadcastForm(StyledForm):
    AUDIENCES = [("students", "All current students"), ("programme", "Students of one programme"),
                 ("applicants", "All applicants"), ("staff", "All staff")]
    audience = forms.ChoiceField(choices=AUDIENCES)
    programme = forms.ModelChoiceField(queryset=Programme.objects.all(), required=False)
    title = forms.CharField(max_length=200)
    body = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}))
    link = forms.CharField(max_length=300, required=False, help_text="Optional link, e.g. /student/fees/")

    def clean(self):
        d = super().clean()
        if d.get("audience") == "programme" and not d.get("programme"):
            self.add_error("programme", "Choose a programme.")
        return d


@staff_required("manage_notifications")
def broadcast(request):
    form = BroadcastForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        users = User.objects.filter(is_active=True)
        if d["audience"] == "students":
            users = users.filter(user_type="student", student__status__counts_as_enrolled=True)
        elif d["audience"] == "programme":
            users = users.filter(user_type="student", student__programme=d["programme"])
        elif d["audience"] == "applicants":
            users = users.filter(user_type="applicant")
        else:
            users = users.filter(user_type="staff")
        users = list(users)
        do_broadcast(users, d["title"], d["body"], d.get("link", ""))
        audit.log(request.user, "notification_broadcast", None, module="notifications",
                  object_repr=f"{d['title']} → {len(users)} recipient(s)")
        messages.success(request, f"Notification sent to {len(users)} user(s).")
        return redirect("notifications:broadcast")
    return render(request, "notifications/broadcast.html", {"form": form})
