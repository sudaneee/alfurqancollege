from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.index, name="index"),
    path("outstanding/", views.outstanding, name="outstanding"),
    path("<slug:key>/", views.view_report, name="view"),
]
