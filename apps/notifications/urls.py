from django.urls import include, path

from apps.core.crud import crud_urlpatterns

from . import views

app_name = "notifications"

urlpatterns = [
    path("notifications/", views.notification_list, name="list"),
    path("notifications/<int:pk>/", views.open_notification, name="open"),
    path("staff/notifications/broadcast/", views.broadcast, name="broadcast"),
    path("staff/notifications/", include(crud_urlpatterns(app_name, views.TEMPLATE_CRUD))),
]
