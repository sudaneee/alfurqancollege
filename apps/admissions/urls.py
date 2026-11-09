from django.urls import include, path

from apps.core.crud import crud_urlpatterns

from . import views

app_name = "admissions"

urlpatterns = [
    # Applicant portal
    path("apply/", views.portal_dashboard, name="portal_dashboard"),
    path("apply/form/", views.portal_form, name="portal_form"),
    path("apply/olevels/", views.portal_olevels, name="portal_olevels"),
    path("apply/documents/", views.portal_documents, name="portal_documents"),
    path("apply/pay/", views.portal_pay, name="portal_pay"),
    path("apply/submit/", views.portal_submit, name="portal_submit"),
    path("apply/offer/", views.portal_offer, name="portal_offer"),
    path("apply/admission-letter/", views.portal_letter, name="portal_letter"),
    # Staff
    path("staff/admissions/", views.staff_list, name="staff_list"),
    path("staff/admissions/new/", views.staff_create, name="staff_create"),
    path("staff/admissions/statistics/", views.statistics, name="statistics"),
    path("staff/admissions/<int:pk>/", views.staff_detail, name="staff_detail"),
    path("staff/admissions/<int:pk>/edit/", views.staff_edit, name="staff_edit"),
    path("staff/admissions/<int:pk>/olevels/", views.staff_olevels, name="staff_olevels"),
    path("staff/admissions/<int:pk>/documents/", views.staff_documents, name="staff_documents"),
    path("staff/admissions/<int:pk>/submit/", views.staff_submit, name="staff_submit"),
    path("staff/admissions/<int:pk>/decide/", views.staff_decide, name="staff_decide"),
    path("staff/admissions/<int:pk>/exempt/", views.staff_exempt, name="staff_exempt"),
    path("staff/admissions/<int:pk>/offer/", views.staff_offer, name="staff_offer"),
    path("staff/admissions/<int:pk>/invoice/", views.staff_invoice, name="staff_invoice"),
    path("staff/admissions/<int:pk>/letter/", views.staff_letter, name="staff_letter"),
    path("staff/admissions/config/", include(crud_urlpatterns(app_name, views.PERIOD_CRUD, views.DOCTYPE_CRUD))),
]
