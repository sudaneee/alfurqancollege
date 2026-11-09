from django.urls import include, path

from apps.core.crud import crud_urlpatterns

from . import views

app_name = "bursary"

urlpatterns = [
    # payer
    path("student/fees/", views.portal_fees, name="portal_fees"),
    path("payments/invoice/<int:pk>/pay/", views.pay_invoice, name="pay_invoice"),
    path("payments/invoice/<int:pk>/pdf/", views.invoice_pdf, name="invoice_pdf"),
    path("payments/callback/", views.callback, name="callback"),
    path("payments/webhook/<slug:gateway>/", views.webhook, name="webhook"),
    path("payments/sandbox/<str:reference>/", views.sandbox_checkout, name="sandbox_checkout"),
    path("payments/receipt/<int:pk>/", views.receipt, name="receipt"),
    # staff
    path("staff/bursary/", views.overview, name="overview"),
    path("staff/bursary/invoices/", views.invoices, name="invoices"),
    path("staff/bursary/invoices/generate/", views.generate_invoices, name="generate_invoices"),
    path("staff/bursary/invoices/<int:pk>/", views.invoice_detail, name="invoice_detail"),
    path("staff/bursary/payments/", views.payments, name="payments"),
    path("staff/bursary/payments/<int:pk>/refund/", views.refund, name="refund"),
    path("staff/bursary/settings/", views.fee_settings, name="settings"),
    path("staff/bursary/config/", include(crud_urlpatterns(app_name, views.CATEGORY_CRUD, views.ITEM_CRUD))),
]
