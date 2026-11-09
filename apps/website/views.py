from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.academics.models import AcademicDocument, CalendarEvent, Programme
from apps.admissions.models import ApplicationPeriod
from apps.core import audit
from apps.core.crud import Crud
from apps.core.forms import StyledForm, StyledModelForm
from apps.core.permissions import staff_required

from .models import ContactMessage, GalleryImage, HeroSlide, Highlight, LeadershipMember, Post


# ---------------------------------------------------------------------------
# Public pages
# ---------------------------------------------------------------------------
def _programmes():
    return Programme.objects.filter(is_published=True).select_related("department")


def home(request):
    posts = Post.visible()
    return render(request, "website/home.html", {
        "slides": HeroSlide.objects.filter(is_active=True),
        "programmes": _programmes(),
        "highlights": Highlight.objects.filter(is_active=True),
        "announcements": posts.filter(category__in=[Post.ANNOUNCEMENT, Post.ADMISSION])[:4],
        "news": posts.filter(category__in=[Post.NEWS, Post.EVENT])[:3],
        "period": ApplicationPeriod.current(),
        "gallery": GalleryImage.objects.filter(is_active=True)[:6],
    })


def about(request):
    return render(request, "website/about.html", {"leaders": LeadershipMember.objects.filter(is_active=True),
                                                  "programmes": _programmes()})


def programmes(request):
    return render(request, "website/programmes.html", {"programmes": _programmes()})


def programme_detail(request, slug):
    p = get_object_or_404(_programmes(), slug=slug)
    courses = p.courses.filter(is_active=True).order_by("year", "term", "code")
    slots = []
    for y in range(1, p.duration_years + 1):
        for t in (1, 2):
            items = [c for c in courses if c.year == y and c.term == t]
            if items:
                slots.append({"label": f"{p.level_name(y)} · {'First' if t == 1 else 'Second'} Semester", "courses": items,
                              "units": sum(c.credit_units for c in items)})
    return render(request, "website/programme_detail.html", {
        "p": p, "slots": slots, "practicals": p.practical_requirements.all(), "others": _programmes().exclude(pk=p.pk),
        "period": ApplicationPeriod.current()})


def admissions(request):
    period = ApplicationPeriod.current()
    upcoming = ApplicationPeriod.objects.filter(is_active=True, opens_on__gt=timezone.localdate()).order_by("opens_on").first()
    return render(request, "website/admissions.html", {
        "period": period, "upcoming": upcoming, "programmes": _programmes(),
        "notices": Post.visible(("public", "applicants")).filter(category=Post.ADMISSION)[:5]})


def news(request):
    qs = Post.visible()
    cat = request.GET.get("category")
    if cat in dict(Post.CATEGORY_CHOICES):
        qs = qs.filter(category=cat)
    page = Paginator(qs, 9).get_page(request.GET.get("page"))
    events = CalendarEvent.objects.filter(is_public=True, start_date__gte=timezone.localdate())[:6]
    return render(request, "website/news.html", {"page": page, "cat": cat, "categories": Post.CATEGORY_CHOICES, "events": events})


def post_detail(request, slug):
    post = get_object_or_404(Post.visible(("public", "students", "applicants", "staff")), slug=slug)
    if post.audience != "public" and not request.user.is_authenticated:
        return redirect(f"/accounts/login/?next={request.path}")
    return render(request, "website/post_detail.html", {"post": post, "recent": Post.visible().exclude(pk=post.pk)[:4]})


class ContactForm(StyledModelForm):
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))  # honeypot

    class Meta:
        model = ContactMessage
        fields = ["name", "email", "phone", "subject", "message"]
        widgets = {"message": forms.Textarea(attrs={"rows": 5})}


def contact(request):
    form = ContactForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if form.cleaned_data.get("website"):  # bot
            return redirect("website:contact")
        msg = form.save()
        from apps.accounts.models import User
        from apps.notifications.services import notify
        for u in User.objects.filter(is_active=True, user_type="staff", groups__permissions__codename="manage_website").distinct()[:20]:
            notify(u, "contact_message", {"subject": msg.subject, "sender": msg.name}, link="/staff/website/messages/",
                   fallback_title=f"New enquiry: {msg.subject}", fallback_body=f"From {msg.name} ({msg.email})")
        messages.success(request, "Thank you. Your message has been received and the College will respond as soon as possible.")
        return redirect("website:contact")
    return render(request, "website/contact.html", {"form": form})


def downloads(request):
    return render(request, "website/downloads.html", {"docs": AcademicDocument.objects.filter(is_public=True)})


# ---------------------------------------------------------------------------
# CMS (staff)
# ---------------------------------------------------------------------------
class SlideForm(StyledModelForm):
    class Meta:
        model = HeroSlide
        fields = ["title", "subtitle", "image", "button_text", "button_url", "order", "is_active"]


class PostForm(StyledModelForm):
    wide_fields = ("summary",)

    class Meta:
        model = Post
        fields = ["title", "category", "audience", "summary", "body", "image", "event_date", "event_venue", "published_at",
                  "is_published", "is_pinned"]
        widgets = {"body": forms.Textarea(attrs={"rows": 10}),
                   "event_date": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
                   "published_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")}


class HighlightForm(StyledModelForm):
    class Meta:
        model = Highlight
        fields = ["title", "text", "icon", "order", "is_active"]


class LeaderForm(StyledModelForm):
    class Meta:
        model = LeadershipMember
        fields = ["name", "position", "photo", "bio", "order", "is_active"]


class GalleryForm(StyledModelForm):
    class Meta:
        model = GalleryImage
        fields = ["title", "image", "order", "is_active"]


PERM = ("manage_website",)
SEC = "Website content"
CRUDS = [
    Crud("post", Post, PostForm, PERM, "News & announcements", "Post", section=SEC,
         description="Publish news, announcements, events and admission notices. Choose the audience to target portals.",
         list_display=[("Title", "title"), ("Category", "category"), ("Audience", "audience"), ("Published", "published_at"),
                       ("Visible", "is_published"), ("Pinned", "is_pinned")], search_fields=["title", "body"]),
    Crud("slide", HeroSlide, SlideForm, PERM, "Homepage slides", "Slide", section=SEC,
         list_display=[("Title", "title"), ("Order", "order"), ("Active", "is_active")]),
    Crud("highlight", Highlight, HighlightForm, PERM, "Why choose us", "Highlight", section=SEC,
         list_display=[("Title", "title"), ("Order", "order"), ("Active", "is_active")]),
    Crud("leader", LeadershipMember, LeaderForm, PERM, "Leadership", "Leader", section=SEC,
         list_display=[("Name", "name"), ("Position", "position"), ("Order", "order"), ("Active", "is_active")]),
    Crud("gallery", GalleryImage, GalleryForm, PERM, "Gallery", "Image", section=SEC,
         list_display=[("Title", "title"), ("Order", "order"), ("Active", "is_active")]),
]


@staff_required("manage_website")
def cms(request):
    return render(request, "website/cms.html", {
        "counts": {"posts": Post.objects.count(), "slides": HeroSlide.objects.count(), "highlights": Highlight.objects.count(),
                   "leaders": LeadershipMember.objects.count(), "gallery": GalleryImage.objects.count(),
                   "unread": ContactMessage.objects.filter(is_handled=False).count()},
        "programmes": Programme.objects.all()})


@staff_required("manage_website")
def contact_messages(request):
    qs = ContactMessage.objects.select_related("handled_by")
    if request.GET.get("open") == "1":
        qs = qs.filter(is_handled=False)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "website/messages.html", {"page": page})


@staff_required("manage_website")
@require_POST
def contact_handled(request, pk):
    m = get_object_or_404(ContactMessage, pk=pk)
    m.is_handled, m.handled_by, m.response_note = True, request.user, request.POST.get("note", "")
    m.save()
    audit.log(request.user, "contact_message_handled", m)
    messages.success(request, "Marked as handled.")
    return redirect("website:messages")
