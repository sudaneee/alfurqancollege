import datetime
import json
import logging

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.academics.models import AcademicSession, Programme
from apps.core import audit
from apps.core.crud import Crud
from apps.core.excel import export_response
from apps.core.pdf import render_pdf
from apps.core.permissions import has_perm, staff_required, student_required
from apps.students.models import Student

from . import forms, services
from .gateways import GATEWAYS, get_gateway
from .models import FeeCategory, FeeItem, GatewaySettings, Invoice, Payment, TransactionLog

logger = logging.getLogger("apps.bursary")

CATEGORY_CRUD = Crud("category", FeeCategory, forms.FeeCategoryForm, ("manage_fees",), "Fee categories", "Fee category",
                     section="Bursary", list_display=[("Category", "name"), ("Code", "code"), ("Active", "is_active")])
ITEM_CRUD = Crud("feeitem", FeeItem, forms.FeeItemForm, ("manage_fees",), "Fee schedule", "Fee item", section="Bursary",
                 description="Every charge is configurable. Leave programme, session or level empty to apply to all.",
                 list_display=[("Fee", "name"), ("Category", "category"), ("Amount (₦)", "amount"), ("Applies to", "scope_label"),
                               ("Stage", "stage"), ("Instalments", "allow_instalments"), ("Active", "is_active")],
                 search_fields=["name", "category__name"], ordering=("category__order", "name"))


def _owns_invoice(user, invoice):
    payer = invoice.payer_user
    return bool(payer and payer.pk == user.pk)


def _invoice_for_payer(request, pk):
    inv = get_object_or_404(Invoice.objects.select_related("student", "application"), pk=pk)
    if not request.user.is_authenticated:
        raise PermissionDenied
    if not _owns_invoice(request.user, inv) and not has_perm(request.user, "view_finance"):
        raise PermissionDenied
    return inv


def _payer_base(request):
    if getattr(request.user, "student", None) is not None and request.user.user_type == "student":
        return "students/portal/base.html"
    return "admissions/portal/base.html"


# ---------------------------------------------------------------------------
# Payer (student / applicant) screens
# ---------------------------------------------------------------------------
@student_required
def portal_fees(request):
    s = request.student
    summary = services.student_financial_summary(s)
    payments = Payment.objects.filter(invoice__student=s).select_related("invoice").order_by("-created_at")
    return render(request, "bursary/portal_fees.html", {"s": s, "fin": summary, "payments": payments,
                                                        "gateway": GatewaySettings.load()})


def pay_invoice(request, pk):
    if not request.user.is_authenticated:
        return redirect(f"{reverse('accounts:route')}?next={request.path}")
    inv = _invoice_for_payer(request, pk)
    cfg = GatewaySettings.load()
    form = forms.PayForm(request.POST or None, initial={"amount": inv.balance})
    if request.method == "POST" and form.is_valid():
        if not cfg.online_payments_enabled:
            messages.error(request, "Online payment is currently unavailable. Please use the bank payment instructions.")
        else:
            try:
                callback = request.build_absolute_uri(reverse("bursary:callback"))
                payment, url = services.initiate_online_payment(inv, form.cleaned_data["amount"], request.user, callback)
                return redirect(url)
            except ValidationError as exc:
                form.add_error("amount", exc)
    return render(request, "bursary/pay.html", {"inv": inv, "form": form, "cfg": cfg, "gateway": get_gateway(),
                                                "minimum": inv.minimum_payment(), "base_template": _payer_base(request)})


def callback(request):
    """Browser return from the gateway. We never trust it: we verify server-side."""
    reference = request.GET.get("reference") or request.GET.get("tx_ref") or request.GET.get("trxref")
    if not reference:
        return HttpResponseBadRequest("Missing payment reference")
    payment = services.confirm_online_payment(reference, source="callback")
    if payment is None:
        messages.error(request, "We could not find that payment.")
        return redirect("accounts:route")
    if payment.status == Payment.SUCCESSFUL:
        messages.success(request, f"Payment of ₦{payment.amount:,.2f} confirmed. Receipt {payment.receipt_number}.")
        return redirect("bursary:receipt", payment.pk) if request.user.is_authenticated else redirect("website:home")
    if payment.status == Payment.FAILED:
        messages.error(request, "The payment was not successful. No money has been recorded. You can try again.")
    else:
        messages.warning(request, "Your payment is being confirmed. If you were debited, it will be updated automatically; check back shortly.")
    if not request.user.is_authenticated:
        return redirect("website:home")
    return redirect("bursary:pay_invoice", payment.invoice_id)


@csrf_exempt
@require_POST
def webhook(request, gateway):
    adapter = GATEWAYS.get(gateway)
    if adapter is None or gateway == "sandbox":
        return HttpResponse(status=404)
    if not adapter.verify_webhook(request):
        TransactionLog.objects.create(reference="", gateway=gateway, event="webhook_bad_signature",
                                      payload={"headers": {k: v for k, v in request.headers.items() if "sign" in k.lower() or "hash" in k.lower()}})
        return HttpResponse(status=401)
    try:
        payload = json.loads(request.body.decode() or "{}")
    except ValueError:
        return HttpResponse(status=400)
    reference = adapter.reference_from_webhook(payload)
    TransactionLog.objects.create(reference=reference or "", gateway=gateway, event="webhook_received", success=True,
                                  payload=payload)
    if reference:
        services.confirm_online_payment(reference, source="webhook")
    return HttpResponse(status=200)


def sandbox_checkout(request, reference):
    """Simulated hosted checkout page (development / demonstration only)."""
    if not settings.ALLOW_SANDBOX_GATEWAY:
        return HttpResponse(status=404)
    payment = get_object_or_404(Payment, reference=reference, gateway="sandbox")
    if request.user.is_authenticated and not (_owns_invoice(request.user, payment.invoice) or has_perm(request.user, "view_finance")):
        raise PermissionDenied
    nxt = request.GET.get("next") or reverse("bursary:callback")
    if request.method == "POST":
        ok = request.POST.get("outcome") == "success"
        TransactionLog.objects.create(payment=payment, reference=reference, gateway="sandbox", event="sandbox_outcome",
                                      success=ok, message="Simulated by tester")
        sep = "&" if "?" in nxt else "?"
        return redirect(f"{nxt}{sep}reference={reference}")
    return render(request, "bursary/sandbox_checkout.html", {"payment": payment})


def receipt(request, pk):
    payment = get_object_or_404(Payment.objects.select_related("invoice__student__programme", "invoice__application"), pk=pk)
    if not request.user.is_authenticated or not (_owns_invoice(request.user, payment.invoice) or has_perm(request.user, "view_finance")):
        raise PermissionDenied
    if payment.status != Payment.SUCCESSFUL:
        messages.error(request, "A receipt is only available for successful payments.")
        return redirect("accounts:route")
    if request.GET.get("pdf") == "1":
        return render_pdf("pdf/receipt.html", {"p": payment, "inv": payment.invoice}, f"receipt_{payment.receipt_number.replace('/', '-')}.pdf", request)
    base = "staff/base.html" if has_perm(request.user, "view_finance") and request.user.user_type == "staff" else _payer_base(request)
    return render(request, "bursary/receipt.html", {"p": payment, "inv": payment.invoice, "base_template": base})


def invoice_pdf(request, pk):
    inv = _invoice_for_payer(request, pk)
    return render_pdf("pdf/invoice.html", {"inv": inv}, f"invoice_{inv.number.replace('/', '-')}.pdf", request)


# ---------------------------------------------------------------------------
# Staff screens
# ---------------------------------------------------------------------------
@staff_required("view_finance")
def overview(request):
    session = AcademicSession.objects.filter(pk=request.GET.get("session")).first() or AcademicSession.current()
    paid = Payment.objects.filter(status=Payment.SUCCESSFUL)
    if session:
        paid = paid.filter(invoice__session=session)
    invoices = Invoice.objects.exclude(status=Invoice.CANCELLED)
    if session:
        invoices = invoices.filter(session=session)
    billed = sum(i.net_amount for i in invoices)
    collected = paid.aggregate(t=Sum("amount"))["t"] or 0
    by_category = []
    for cat in FeeCategory.objects.all():
        lines = sum((l.amount for l in cat.invoiceline_set.filter(invoice__in=invoices)), 0)
        by_category.append({"name": cat.name, "billed": lines})
    by_method = paid.values("method").annotate(total=Sum("amount"), n=Count("id")).order_by("-total")
    by_programme = (paid.filter(invoice__student__isnull=False).values("invoice__student__programme__name")
                    .annotate(total=Sum("amount")).order_by("-total"))
    top = max([r["total"] for r in by_programme] or [1])
    for r in by_programme:
        r["pct"] = round(float(r["total"]) * 100 / float(top))
    debtors = sorted([i for i in invoices.filter(status__in=[Invoice.UNPAID, Invoice.PART_PAID], student__isnull=False).select_related("student")],
                     key=lambda i: -i.balance)[:10]
    return render(request, "bursary/overview.html", {
        "session": session, "sessions": AcademicSession.objects.all(), "billed": billed, "collected": collected,
        "outstanding": max(0, billed - collected), "pending": Payment.objects.filter(status=Payment.PENDING).exclude(method="online").count(),
        "by_category": by_category, "by_method": by_method, "by_programme": by_programme, "debtors": debtors,
        "rate": round(float(collected) * 100 / float(billed)) if billed else 0,
        "recent": Payment.objects.filter(status=Payment.SUCCESSFUL).select_related("invoice__student", "invoice__application").order_by("-paid_at")[:8],
    })


def _invoice_qs(request):
    qs = Invoice.objects.select_related("student__programme", "application", "session")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(number__icontains=q) | Q(student__matric_number__icontains=q) | Q(student__last_name__icontains=q)
                       | Q(student__first_name__icontains=q) | Q(application__application_number__icontains=q)
                       | Q(application__last_name__icontains=q))
    for key, field in (("status", "status"), ("session", "session_id"), ("programme", "student__programme_id"), ("purpose", "purpose")):
        if request.GET.get(key):
            qs = qs.filter(**{field: request.GET[key]})
    return qs


@staff_required("view_finance")
def invoices(request):
    qs = _invoice_qs(request)
    if request.GET.get("export") == "xlsx":
        rows = [[i.number, i.payer_reference, i.payer_name, i.student.programme.name if i.student_id else "Applicant", i.session,
                 i.description, i.gross_amount, i.adjustments_total, i.net_amount, i.amount_paid, i.balance, i.get_status_display()] for i in qs]
        return export_response("invoices.xlsx", ["Invoice", "Matric / App No.", "Name", "Programme", "Session", "Description",
                                                 "Gross", "Adjustments", "Net", "Paid", "Balance", "Status"], rows)
    page = Paginator(qs.order_by("-created_at"), 30).get_page(request.GET.get("page"))
    return render(request, "bursary/invoices.html", {"page": page, "sessions": AcademicSession.objects.all(),
                                                     "programmes": Programme.objects.all(), "statuses": Invoice.STATUS_CHOICES,
                                                     "q": request.GET.get("q", "")})


@staff_required("view_finance")
def invoice_detail(request, pk):
    inv = get_object_or_404(Invoice.objects.select_related("student__programme", "application", "session"), pk=pk)
    pay_form = forms.OfflinePaymentForm(initial={"amount": inv.balance, "verify": has_perm(request.user, "verify_payments")})
    adj_form = forms.AdjustmentForm()
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "record_payment":
                if not has_perm(request.user, "record_payments"):
                    raise PermissionDenied
                pay_form = forms.OfflinePaymentForm(request.POST, request.FILES)
                if pay_form.is_valid():
                    d = pay_form.cleaned_data
                    paid_at = timezone.make_aware(datetime.datetime.combine(d["paid_on"], datetime.time(12))) if d.get("paid_on") else None
                    p = services.record_offline_payment(inv, d["amount"], d["method"], d.get("reference"), request.user,
                                                        paid_at=paid_at, note=d.get("note", ""), evidence=d.get("evidence"),
                                                        verify=d.get("verify") and has_perm(request.user, "verify_payments"))
                    messages.success(request, f"Payment {p.reference} recorded ({p.get_status_display()}).")
                    return redirect("bursary:invoice_detail", pk)
            elif action == "adjust":
                if not has_perm(request.user, "manage_adjustments"):
                    raise PermissionDenied
                adj_form = forms.AdjustmentForm(request.POST)
                if adj_form.is_valid():
                    d = adj_form.cleaned_data
                    services.add_adjustment(inv, d["kind"], d["amount"], d["reason"], request.user, d.get("sponsor", ""))
                    messages.success(request, "Adjustment applied.")
                    return redirect("bursary:invoice_detail", pk)
            elif action == "cancel":
                if not has_perm(request.user, "manage_fees"):
                    raise PermissionDenied
                services.cancel_invoice(inv, request.user, request.POST.get("reason", ""))
                messages.success(request, "Invoice cancelled.")
                return redirect("bursary:invoice_detail", pk)
            elif action == "refresh":
                if inv.student_id and inv.session_id and inv.status != Invoice.CANCELLED:
                    services.generate_student_invoice(inv.student, inv.session, request.user,
                                                      stage=FeeItem.ACCEPTANCE if inv.purpose == "acceptance" else FeeItem.STUDENT)
                    messages.success(request, "Invoice refreshed from the current fee schedule (new items only).")
                return redirect("bursary:invoice_detail", pk)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
    return render(request, "bursary/invoice_detail.html", {
        "inv": inv, "lines": inv.lines.select_related("category"), "adjustments": inv.adjustments.select_related("approved_by"),
        "payments": inv.payments.select_related("initiated_by", "verified_by").prefetch_related("refunds"),
        "pay_form": pay_form, "adj_form": adj_form, "refund_form": forms.RefundForm()})


@staff_required("record_payments", "manage_fees")
def generate_invoices(request):
    student = Student.objects.filter(pk=request.GET.get("student")).first()
    form = forms.GenerateInvoicesForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        if student:
            students = [student]
        else:
            qs = Student.objects.filter(status__counts_as_enrolled=True)
            if d.get("programme"):
                qs = qs.filter(programme=d["programme"])
            if d.get("year"):
                qs = qs.filter(current_year=d["year"])
            students = list(qs)
        created = 0
        for s in students:
            before = Invoice.objects.filter(student=s, session=d["session"]).count()
            inv = services.generate_student_invoice(s, d["session"], request.user, stage=d["stage"])
            if inv and Invoice.objects.filter(student=s, session=d["session"]).count() > before:
                created += 1
        audit.log(request.user, "invoices_generated", None, module="bursary",
                  object_repr=f"{created} new invoice(s) for {len(students)} student(s), {d['session']}")
        messages.success(request, f"{created} new invoice(s) generated; {len(students) - created} student(s) already had one (new fee items were added where applicable).")
        if student:
            return redirect(f"/staff/students/{student.pk}/?tab=finance")
        return redirect("bursary:invoices")
    return render(request, "bursary/generate.html", {"form": form, "student": student})


@staff_required("view_finance")
def payments(request):
    qs = Payment.objects.select_related("invoice__student", "invoice__application", "initiated_by", "verified_by")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(reference__icontains=q) | Q(receipt_number__icontains=q) | Q(invoice__number__icontains=q)
                       | Q(invoice__student__matric_number__icontains=q) | Q(invoice__student__last_name__icontains=q))
    for key, field in (("status", "status"), ("method", "method")):
        if request.GET.get(key):
            qs = qs.filter(**{field: request.GET[key]})
    if request.GET.get("from"):
        qs = qs.filter(created_at__date__gte=request.GET["from"])
    if request.GET.get("to"):
        qs = qs.filter(created_at__date__lte=request.GET["to"])
    if request.method == "POST":
        if not has_perm(request.user, "verify_payments"):
            raise PermissionDenied
        approve = request.POST.get("decision") == "approve"
        done = 0
        for p in Payment.objects.filter(pk__in=request.POST.getlist("selected"), status=Payment.PENDING).exclude(method="online"):
            try:
                services.verify_offline_payment(p, request.user, approve, request.POST.get("note", ""))
                done += 1
            except ValidationError:
                pass
        messages.success(request, f"{done} payment(s) {'verified' if approve else 'rejected'}.")
        return redirect(request.get_full_path())
    if request.GET.get("export") == "xlsx":
        rows = [[p.created_at, p.paid_at, p.reference, p.receipt_number, p.invoice.number, p.invoice.payer_reference, p.invoice.payer_name,
                 p.get_method_display(), p.amount, p.get_status_display(), p.initiated_by, p.verified_by,
                 "Staff" if p.via_staff else "Self"] for p in qs]
        return export_response("payments.xlsx", ["Created", "Paid", "Reference", "Receipt", "Invoice", "Matric / App No.", "Payer",
                                                 "Method", "Amount", "Status", "Recorded by", "Verified by", "Channel"], rows)
    totals = qs.filter(status=Payment.SUCCESSFUL).aggregate(t=Sum("amount"), n=Count("id"))
    page = Paginator(qs.order_by("-created_at"), 30).get_page(request.GET.get("page"))
    return render(request, "bursary/payments.html", {"page": page, "statuses": Payment.STATUS_CHOICES, "methods": Payment.METHOD_CHOICES,
                                                     "totals": totals, "q": q})


@staff_required("manage_refunds")
@require_POST
def refund(request, pk):
    p = get_object_or_404(Payment, pk=pk)
    form = forms.RefundForm(request.POST)
    if form.is_valid():
        try:
            services.record_refund(p, form.cleaned_data["amount"], form.cleaned_data["reason"], request.user, form.cleaned_data.get("reference", ""))
            messages.success(request, "Refund recorded and the invoice balance updated.")
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
    return redirect("bursary:invoice_detail", p.invoice_id)


@staff_required("manage_fees")
def fee_settings(request):
    cfg = GatewaySettings.load()
    form = forms.GatewaySettingsForm(request.POST or None, instance=cfg)
    if request.method == "POST" and form.is_valid():
        before = audit.snapshot(GatewaySettings.load())
        saved = form.save()
        audit.log(request.user, "gateway_settings_updated", saved, changes=audit.diff(before, audit.snapshot(saved)))
        messages.success(request, "Payment settings saved.")
        return redirect("bursary:settings")
    keys = {"paystack": bool(settings.PAYSTACK_SECRET_KEY), "flutterwave": bool(settings.FLUTTERWAVE_SECRET_KEY),
            "sandbox": settings.ALLOW_SANDBOX_GATEWAY}
    return render(request, "bursary/settings.html", {"form": form, "keys": keys,
                                                     "items": FeeItem.objects.select_related("category", "session").prefetch_related("programmes"),
                                                     "categories": FeeCategory.objects.all(),
                                                     "logs": TransactionLog.objects.all()[:15]})
