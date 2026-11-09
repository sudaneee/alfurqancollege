from django.templatetags.static import static

from .models import SiteSettings


def site(request):
    s = SiteSettings.load()
    ctx = {
        "site": s,
        "site_logo": s.logo.url if s.logo else static("img/logo.jpg"),
    }
    match = getattr(request, "resolver_match", None)
    if match is not None and match.namespace == "website":
        from apps.academics.models import Programme

        ctx["nav_programmes"] = Programme.objects.filter(is_published=True).only("name", "slug")
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        ctx["unread_notifications"] = user.notifications.filter(is_read=False).count()
    return ctx
