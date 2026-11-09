from django.urls import path

from . import views

app_name = "registration"

urlpatterns = [
    path("student/courses/", views.portal_courses, name="portal_courses"),
    path("registration/<int:pk>/slip/", views.slip, name="slip"),
    path("staff/registration/", views.staff_list, name="staff_list"),
    path("staff/registration/student/<int:pk>/", views.staff_student, name="staff_student"),
    path("staff/registration/<int:pk>/review/", views.staff_review, name="staff_review"),
]
