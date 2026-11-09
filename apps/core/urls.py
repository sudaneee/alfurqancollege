from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("system/", views.system, name="system"),
    path("system/settings/", views.settings_edit, name="settings"),
    path("system/audit/", views.audit_log, name="audit_log"),
    path("search/", views.search, name="search"),
    path("bulk/<slug:kind>/", views.bulk_home, name="bulk_home"),
    path("bulk/<slug:kind>/template/", views.bulk_template, name="bulk_template"),
    path("bulk/batch/<int:pk>/", views.bulk_preview, name="bulk_preview"),
    path("bulk/batch/<int:pk>/confirm/", views.bulk_confirm, name="bulk_confirm"),
    path("bulk/batch/<int:pk>/cancel/", views.bulk_cancel, name="bulk_cancel"),
    path("bulk/batch/<int:pk>/failed.xlsx", views.bulk_failed, name="bulk_failed"),
]
