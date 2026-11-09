from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Alfurqan College — technical administration"
admin.site.site_title = "Alfurqan College"

urlpatterns = [
    path("django-admin/", admin.site.urls),  # technical fallback; daily work happens in the Staff Portal
    path("staff/academics/", include("apps.academics.urls")),
    path("staff/reports/", include("apps.reports.urls")),
    path("staff/", include("apps.core.urls")),
    path("", include("apps.accounts.urls")),
    path("", include("apps.admissions.urls")),
    path("", include("apps.students.urls")),
    path("", include("apps.registration.urls")),
    path("", include("apps.results.urls")),
    path("", include("apps.bursary.urls")),
    path("", include("apps.notifications.urls")),
    path("", include("apps.website.urls")),
]

handler403 = "apps.core.views.error_403"
handler404 = "apps.core.views.error_404"
handler500 = "apps.core.views.error_500"

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
