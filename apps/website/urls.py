from django.urls import include, path

from apps.core.crud import crud_urlpatterns

from . import views

app_name = "website"

urlpatterns = [
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("programmes/", views.programmes, name="programmes"),
    path("programmes/<slug:slug>/", views.programme_detail, name="programme_detail"),
    path("admissions/", views.admissions, name="admissions"),
    path("news/", views.news, name="news"),
    path("news/<slug:slug>/", views.post_detail, name="post_detail"),
    path("contact/", views.contact, name="contact"),
    path("downloads/", views.downloads, name="downloads"),
    # CMS
    path("staff/website/", views.cms, name="cms"),
    path("staff/website/messages/", views.contact_messages, name="messages"),
    path("staff/website/messages/<int:pk>/handled/", views.contact_handled, name="message_handled"),
    path("staff/website/", include(crud_urlpatterns(app_name, *views.CRUDS))),
]
