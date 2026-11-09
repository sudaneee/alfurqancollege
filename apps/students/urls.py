from django.urls import include, path

from apps.core.crud import crud_urlpatterns

from . import views

app_name = "students"

staff = [
    path("staff/students/", views.student_list, name="list"),
    path("staff/students/new/", views.student_create, name="create"),
    path("staff/students/promote/", views.promote, name="promote"),
    path("staff/students/<int:pk>/", views.student_detail, name="detail"),
    path("staff/students/<int:pk>/edit/", views.student_edit, name="edit"),
    path("staff/students/<int:pk>/status/", views.student_status, name="status"),
    path("staff/students/<int:pk>/documents/", views.student_document_upload, name="document_upload"),
    path("staff/students/<int:pk>/documents/<int:doc_id>/verify/", views.student_document_verify, name="document_verify"),
]

portal = [
    path("student/", views.portal_dashboard, name="portal_dashboard"),
    path("student/profile/", views.portal_profile, name="portal_profile"),
    path("student/documents/", views.portal_documents, name="portal_documents"),
    path("student/announcements/", views.portal_announcements, name="portal_announcements"),
]

# Student status configuration lives under /staff/students/config/
urlpatterns = staff + portal + [path("staff/students/config/", include(crud_urlpatterns(app_name, views.STATUS_CRUD)))]
