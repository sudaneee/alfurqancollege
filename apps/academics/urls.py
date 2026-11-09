from django.urls import path

from apps.core.crud import crud_urlpatterns

from . import views

app_name = "academics"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("programmes/<int:pk>/curriculum/", views.curriculum, name="curriculum"),
    path("allocations/", views.allocations, name="allocations"),
    path("allocations/<int:pk>/delete/", views.allocation_delete, name="allocation_delete"),
] + crud_urlpatterns(app_name, *views.CRUDS)
