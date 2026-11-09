from django.urls import include, path

from apps.core.crud import crud_urlpatterns

from . import views

app_name = "results"

urlpatterns = [
    path("student/results/", views.portal_results, name="portal_results"),
    path("staff/results/", views.staff_list, name="staff_list"),
    path("staff/results/my-courses/", views.my_courses, name="my_courses"),
    path("staff/results/open/<int:course_id>/<int:semester_id>/", views.open_sheet, name="open_sheet"),
    path("staff/results/sheet/<int:pk>/", views.sheet_detail, name="sheet"),
    path("staff/results/broadsheet/", views.broadsheet, name="broadsheet"),
    path("staff/results/transcript/<int:pk>/", views.transcript, name="transcript"),
    path("staff/results/config/", include(crud_urlpatterns(app_name, views.SCHEME_CRUD))),
]
