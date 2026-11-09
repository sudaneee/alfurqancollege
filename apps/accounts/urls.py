from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("apply/login/", views.applicant_login, name="applicant_login"),
    path("apply/register/", views.applicant_signup, name="applicant_signup"),
    path("student/login/", views.student_login, name="student_login"),
    path("staff/login/", views.staff_login, name="staff_login"),
    path("accounts/login/", views.login_chooser, name="login"),
    path("accounts/logout/", views.logout_view, name="logout"),
    path("accounts/route/", views.route, name="route"),
    path("accounts/password/change/", views.password_change, name="password_change"),
    # user & role management (staff portal)
    path("staff/users/", views.user_list, name="user_list"),
    path("staff/users/new/", views.user_create, name="user_create"),
    path("staff/users/<int:pk>/", views.user_detail, name="user_detail"),
    path("staff/users/<int:pk>/edit/", views.user_edit, name="user_edit"),
    path("staff/users/<int:pk>/toggle/", views.user_toggle_active, name="user_toggle"),
    path("staff/users/<int:pk>/reset-password/", views.user_reset_password, name="user_reset_password"),
    path("staff/roles/", views.role_list, name="role_list"),
    path("staff/roles/new/", views.role_form, name="role_create"),
    path("staff/roles/<int:pk>/", views.role_form, name="role_edit"),
    path("staff/roles/<int:pk>/delete/", views.role_delete, name="role_delete"),
]
