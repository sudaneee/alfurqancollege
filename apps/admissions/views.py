"""Admissions: applicant self-service and staff-assisted operations.

Both modes use the same handlers (`_edit_biodata`, `_edit_olevels`,
`_documents`) and the same services; only the template wrapper and the
permission check differ. Every action records who performed it.
"""
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.academics.models import Programme
from apps.accounts.models import User
from apps.core import audit
from apps.core.crud import Crud
from apps.core.excel import export_response
from apps.core.models import AuditLog
from apps.core.pdf import render_pdf
from apps.core.permissions import applicant_required, has_perm, staff_required
from apps.students.forms import DocumentTypeForm
from apps.students.models import DocumentType
from apps.students.services import temporary_password

from . import forms, services
from .models import Application, ApplicationDocument, ApplicationPeriod

PERIOD_CRUD = Crud("period", ApplicationPeriod, forms.PeriodForm, ("manage_admission_settings",), "Application periods",
                   "Application period", section="Admissions",
                   description="Open and close admission exercises, set the application fee (0 = free) and choose programmes.",
                   list_display=[("Period", "name"), ("Session", "session"), ("Opens", "opens_on"), ("Closes", "closes_on"),
                                 ("Fee", "application_fee"), ("Active", "is_active")])
DOCTYPE_CRUD = Crud("doctype", DocumentType, DocumentTypeForm, ("manage_admission_settings", "manage_settings"),
                    "Document types", "Document type", section="Admissions",
                    list_display=[("Document", "name"), ("Required for application", "required_for_application"),
                                  ("Required for students", "required_for_students")])

STEPS = [("biodata", "Biodata", "bi-person"), ("olevels", "O'Level results", "bi-journal-text"),
         ("documents", "Documents", "bi-folder2"), ("payment", "Application fee", "bi-credit-card"),
         ("submit", "Submit", "bi-send")]


def _steps(app):
    done = {
        "biodata": bool(app and app.first_name and app.date_of_birth and app.phone and app.address),
        "olevels": bool(app and app.olevels.count() >= 5),
        "documents": bool(app and not DocumentType.objects.filter(required_for_application=True).exclude(
            pk__in=app.documents.values_list("document_type_id", flat=True)).exists()),
        "payment": bool(app and app.fee_settled),
        "submit": bool(app and app.status != Application.DRAFT),
    }
    out, current_set = [], False
    for key, label, icon in STEPS:
        state = "done" if done[key] else ("current" if not current_set else "")
        if not done[key]:
            current_set = True
        out.append({"key": key, "label": label, "icon": icon, "state": state})
    return out


def _ctx(request, app, mode):
    staff = mode == "staff"
    return {
        "app": app, "mode": mode, "staff": staff,
        "base_template": "staff/base.html" if staff else "admissions/portal/base.html",
        "back_url": f"/staff/admissions/{app.pk}/" if staff else "/apply/",
    }


# ---------------------------------------------------------------------------
# Shared handlers
# ---------------------------------------------------------------------------
def _edit_biodata(request, app, mode):
    if mode == "portal" and not app.is_editable_by_applicant:
        messages.info(request, "Your application can no longer be edited.")
        return redirect("admissions:portal_dashboard")
    form = forms.ApplicationForm(request.POST or None, instance=app, period=app.period)
    if mode == "staff":
        for f in ("gender", "date_of_birth", "phone", "address", "state_of_origin"):
            form.fields[f].required = False
    if request.method == "POST" and form.is_valid():
        before = audit.snapshot(Application.objects.get(pk=app.pk))
        saved = form.save()
        u = saved.user
        u.first_name, u.last_name, u.other_names, u.phone = saved.first_name, saved.last_name, saved.middle_name, saved.phone
        u.save(update_fields=["first_name", "last_name", "other_names", "phone"])
        changes = audit.diff(before, audit.snapshot(saved))
        if changes:
            audit.log(request.user, "application_updated", saved, changes=changes, on_behalf_of=saved.user)
            services.record_event(saved, "Biodata updated", request.user)
        messages.success(request, "Details saved.")
        return redirect(f"/staff/admissions/{app.pk}/" if mode == "staff" else "admissions:portal_olevels")
    return render(request, "admissions/biodata.html", _ctx(request, app, mode) | {"form": form})


def _edit_olevels(request, app, mode):
    if mode == "portal" and not app.is_editable_by_applicant:
        return redirect("admissions:portal_dashboard")
    formset = forms.OLevelFormSet(request.POST or None, instance=app)
    if request.method == "POST" and formset.is_valid():
        with transaction.atomic():
            formset.save()
        services.record_event(app, "O'Level results updated", request.user)
        audit.log(request.user, "olevels_updated", app, on_behalf_of=app.user)
        messages.success(request, f"O'Level results saved ({app.olevels.count()} subjects, {app.credit_count} credits).")
        return redirect(f"/staff/admissions/{app.pk}/" if mode == "staff" else "admissions:portal_documents")
    return render(request, "admissions/olevels.html", _ctx(request, app, mode) | {"formset": formset})


def _documents(request, app, mode):
    editable = mode == "staff" or app.is_editable_by_applicant
    form = forms.ApplicationDocumentForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and editable:
        if "delete" in request.POST:
            doc = get_object_or_404(ApplicationDocument, pk=request.POST["delete"], application=app)
            doc.delete()
            services.record_event(app, f"Document removed: {doc.document_type}", request.user)
            messages.success(request, "Document removed.")
            return redirect(request.path)
        if form.is_valid():
            dt = form.cleaned_data["document_type"]
            ApplicationDocument.objects.filter(application=app, document_type=dt).delete()  # replace
            doc = form.save(commit=False)
            doc.application, doc.uploaded_by = app, request.user
            doc.save()
            services.record_event(app, f"Document uploaded: {dt}", request.user)
            audit.log(request.user, "application_document_uploaded", app, on_behalf_of=app.user, note=str(dt))
            messages.success(request, f"{dt} uploaded.")
            return redirect(request.path)
    required = DocumentType.objects.filter(required_for_application=True)
    have = set(app.documents.values_list("document_type_id", flat=True))
    return render(request, "admissions/documents.html", _ctx(request, app, mode) | {
        "form": form, "docs": app.documents.select_related("document_type", "uploaded_by"), "editable": editable,
        "missing": [d for d in required if d.id not in have]})


# ---------------------------------------------------------------------------
# Applicant portal
# ---------------------------------------------------------------------------
def _my_application(request):
    period = ApplicationPeriod.current()
    app = None
    if period:
        app = Application.objects.filter(user=request.user, period=period).first()
    if app is None:
        app = Application.objects.filter(user=request.user).order_by("-created_at").first()
    return period, app


@applicant_required
def portal_dashboard(request):
    period, app = _my_application(request)
    if request.method == "POST" and "start" in request.POST:
        if not period:
            messages.error(request, "Applications are currently closed.")
        elif Application.objects.filter(user=request.user, period=period).exists():
            pass
        else:
            u = request.user
            first = period.programmes.filter(accepting_applications=True).first()
            prog = Programme.objects.filter(pk=request.POST.get("programme"), application_periods=period).first() or first
            app = Application.objects.create(user=u, period=period, first_choice=prog, first_name=u.first_name,
                                             last_name=u.last_name, email=u.email, phone=u.phone, created_by=u)
            services.record_event(app, "Application started", u)
            return redirect("admissions:portal_form")
        return redirect("admissions:portal_dashboard")
    student = getattr(request.user, "student", None)
    return render(request, "admissions/portal/dashboard.html", {
        "period": period, "app": app, "steps": _steps(app) if app else [], "student": student,
        "programmes": period.programmes.filter(accepting_applications=True) if period else [],
        "invoice": app.fee_invoice if app else None,
        "missing": app.missing_items() if app and app.status == Application.DRAFT else [],
    })


def _require_app(request):
    _, app = _my_application(request)
    if app is None:
        messages.info(request, "Start your application first.")
    return app


@applicant_required
def portal_form(request):
    app = _require_app(request)
    return _edit_biodata(request, app, "portal") if app else redirect("admissions:portal_dashboard")


@applicant_required
def portal_olevels(request):
    app = _require_app(request)
    return _edit_olevels(request, app, "portal") if app else redirect("admissions:portal_dashboard")


@applicant_required
def portal_documents(request):
    app = _require_app(request)
    return _documents(request, app, "portal") if app else redirect("admissions:portal_dashboard")


@applicant_required
def portal_pay(request):
    app = _require_app(request)
    if not app:
        return redirect("admissions:portal_dashboard")
    from apps.bursary.services import ensure_application_invoice
    inv = ensure_application_invoice(app, request.user)
    if inv is None or inv.status == "paid":
        messages.info(request, "No application fee is due.")
        return redirect("admissions:portal_dashboard")
    return redirect("bursary:pay_invoice", inv.pk)


@applicant_required
@require_POST
def portal_submit(request):
    app = _require_app(request)
    if app:
        try:
            services.submit(app, request.user)
            messages.success(request, f"Application submitted. Your application number is {app.application_number}.")
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
    return redirect("admissions:portal_dashboard")


@applicant_required
@require_POST
def portal_offer(request):
    app = _require_app(request)
    if app:
        accept = request.POST.get("response") == "accept"
        try:
            student = services.respond_to_offer(app, accept, request.user)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            if student:
                messages.success(request, f"Congratulations! You have accepted admission. Your matric number is "
                                          f"{student.matric_number}. You can now use the Student Portal.")
                return redirect("students:portal_dashboard")
            messages.info(request, "You have declined the admission offer.")
    return redirect("admissions:portal_dashboard")


def _letter_response(request, app):
    if app.status != Application.ADMITTED:
        raise PermissionDenied("An admission letter is only available for admitted applicants.")
    return render_pdf("pdf/admission_letter.html", {"app": app, "student": getattr(app, "student", None)},
                      f"admission_letter_{app.pk}.pdf", request)


@applicant_required
def portal_letter(request):
    app = _require_app(request)
    return _letter_response(request, app) if app else redirect("admissions:portal_dashboard")


# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------
def _staff_app(pk):
    return get_object_or_404(Application.objects.select_related("period__session", "first_choice", "second_choice",
                                                                "admitted_programme", "user"), pk=pk)


@staff_required("view_applications", "process_admissions")
def staff_list(request):
    qs = Application.objects.select_related("first_choice", "admitted_programme", "period")
    periods = ApplicationPeriod.objects.all()
    period_id = request.GET.get("period") or (ApplicationPeriod.current().pk if ApplicationPeriod.current() else "")
    if period_id:
        qs = qs.filter(period_id=period_id)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(application_number__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)
                       | Q(phone__icontains=q) | Q(email__icontains=q))
    for key, field in (("status", "status"), ("programme", "first_choice_id"), ("offer", "offer_status")):
        if request.GET.get(key):
            qs = qs.filter(**{field: request.GET[key]})
    if request.method == "POST" and has_perm(request.user, "process_admissions"):
        ids = request.POST.getlist("selected")
        decision = request.POST.get("bulk_decision")
        ok = failed = 0
        for app in Application.objects.filter(pk__in=ids):
            try:
                services.decide(app, decision, request.user, note=request.POST.get("bulk_note", ""))
                ok += 1
            except ValidationError:
                failed += 1
        messages.success(request, f"{ok} application(s) updated." + (f" {failed} skipped (not eligible)." if failed else ""))
        return redirect(request.get_full_path())
    if request.GET.get("export") == "xlsx":
        headers = ["Application No.", "Surname", "First Name", "Middle Name", "Gender", "Date of Birth", "Phone", "Email",
                   "State", "First Choice", "Second Choice", "O'Level Credits", "Fee", "Status", "Admitted Into", "Offer",
                   "Submitted", "Sample"]
        rows = [[a.application_number, a.last_name, a.first_name, a.middle_name, a.get_gender_display(), a.date_of_birth,
                 a.phone, a.email, a.state_of_origin, a.first_choice.name, a.second_choice.name if a.second_choice else "",
                 a.credit_count, "Exempt" if a.fee_exempt else ("Paid" if a.fee_settled else "Unpaid"),
                 a.get_status_display(), a.admitted_programme.name if a.admitted_programme else "", a.get_offer_status_display(),
                 a.submitted_at, "Yes" if a.is_sample else ""] for a in qs.prefetch_related("olevels")]
        return export_response("applications.xlsx", headers, rows, "Applications")
    stats = dict(qs.values_list("status").annotate(n=Count("id")))
    page = Paginator(qs.order_by("-submitted_at", "-created_at"), 30).get_page(request.GET.get("page"))
    return render(request, "admissions/staff/list.html", {
        "page": page, "periods": periods, "period_id": str(period_id), "programmes": Programme.objects.all(),
        "statuses": Application.STATUS_CHOICES, "stats": stats, "q": q,
    })


@staff_required("process_admissions")
def staff_create(request):
    form = forms.StaffApplicationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        with transaction.atomic():
            email = (d.get("email") or "").strip().lower()
            username = email or f"app-{temporary_password().lower()}"
            user = User(username=username, email=email, first_name=d["first_name"], last_name=d["last_name"],
                        other_names=d.get("middle_name", ""), phone=d.get("phone", ""), user_type=User.APPLICANT,
                        must_change_password=True)
            temp = temporary_password()
            user.set_password(temp)
            user.save()
            app = form.save(commit=False)
            app.user, app.period, app.created_by = user, d["period"], request.user
            app.save()
            services.assign_number(app)
            services.record_event(app, "Application created by staff", request.user)
            audit.log(request.user, "applicant_created", app, on_behalf_of=user)
        messages.success(request, f"Applicant {app.application_number} created. Portal sign-in: {username} / {temp}. "
                                  "Now add O'Level results and documents, then submit on their behalf.")
        return redirect("admissions:staff_detail", app.pk)
    return render(request, "admissions/staff/create.html", {"form": form})


@staff_required("view_applications", "process_admissions")
def staff_detail(request, pk):
    app = _staff_app(pk)
    return render(request, "admissions/staff/detail.html", {
        "app": app, "steps": _steps(app), "missing": app.missing_items() if app.status == Application.DRAFT else [],
        "decision_form": forms.DecisionForm(initial={"programme": app.admitted_programme or app.first_choice}),
        "exempt_form": forms.ExemptionForm(), "offer_form": forms.OfferOnBehalfForm(),
        "events": app.events.select_related("actor"), "invoice": app.fee_invoice,
        "audit": AuditLog.objects.filter(object_type="admissions.Application", object_id=str(app.pk)).select_related("actor")[:20],
    })


@staff_required("process_admissions")
def staff_edit(request, pk):
    return _edit_biodata(request, _staff_app(pk), "staff")


@staff_required("process_admissions")
def staff_olevels(request, pk):
    return _edit_olevels(request, _staff_app(pk), "staff")


@staff_required("process_admissions")
def staff_documents(request, pk):
    return _documents(request, _staff_app(pk), "staff")


@staff_required("process_admissions")
@require_POST
def staff_submit(request, pk):
    app = _staff_app(pk)
    force = request.POST.get("force") == "1"
    try:
        services.submit(app, request.user, force=force)
        messages.success(request, f"Application {app.application_number} submitted on the applicant's behalf.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages) + " Tick 'submit anyway' to override (recorded).")
    return redirect("admissions:staff_detail", pk)


@staff_required("process_admissions")
@require_POST
def staff_decide(request, pk):
    app = _staff_app(pk)
    form = forms.DecisionForm(request.POST)
    if form.is_valid():
        try:
            services.decide(app, form.cleaned_data["decision"], request.user, form.cleaned_data.get("programme"),
                            form.cleaned_data.get("note", ""))
            messages.success(request, "Decision recorded and the applicant has been notified.")
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
    return redirect("admissions:staff_detail", pk)


@staff_required("grant_fee_exemption")
@require_POST
def staff_exempt(request, pk):
    app = _staff_app(pk)
    form = forms.ExemptionForm(request.POST)
    if form.is_valid():
        services.grant_fee_exemption(app, request.user, form.cleaned_data["reason"])
        messages.success(request, "Application fee exemption granted.")
    else:
        messages.error(request, "Give a reason for the exemption.")
    return redirect("admissions:staff_detail", pk)


@staff_required("process_admissions")
@require_POST
def staff_offer(request, pk):
    app = _staff_app(pk)
    form = forms.OfferOnBehalfForm(request.POST)
    if form.is_valid():
        try:
            student = services.respond_to_offer(app, form.cleaned_data["response"] == "accept", request.user,
                                                matric_number=form.cleaned_data.get("matric_number") or None)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            if student:
                messages.success(request, f"Admission accepted on behalf of the applicant. Student record created: {student.matric_number}.")
                return redirect("students:detail", student.pk)
            messages.info(request, "Offer declined on behalf of the applicant.")
    return redirect("admissions:staff_detail", pk)


@staff_required("process_admissions")
@require_POST
def staff_invoice(request, pk):
    app = _staff_app(pk)
    from apps.bursary.services import ensure_application_invoice
    inv = ensure_application_invoice(app, request.user)
    if inv is None:
        messages.info(request, "No application fee applies (free form or exempted).")
        return redirect("admissions:staff_detail", pk)
    return redirect("bursary:invoice_detail", inv.pk)


@staff_required("view_applications", "process_admissions")
def staff_letter(request, pk):
    return _letter_response(request, _staff_app(pk))


@staff_required("view_applications")
def statistics(request):
    period_id = request.GET.get("period") or (ApplicationPeriod.current().pk if ApplicationPeriod.current() else None)
    qs = Application.objects.filter(period_id=period_id) if period_id else Application.objects.all()
    by_prog = (qs.exclude(status=Application.DRAFT).values("first_choice__name")
               .annotate(total=Count("id"), admitted=Count("id", filter=Q(status=Application.ADMITTED)),
                         accepted=Count("id", filter=Q(offer_status=Application.OFFER_ACCEPTED))).order_by("first_choice__name"))
    return render(request, "admissions/staff/statistics.html", {"by_prog": by_prog, "periods": ApplicationPeriod.objects.all(),
                                                                "period_id": str(period_id or ""),
                                                                "by_status": qs.values("status").annotate(n=Count("id"))})
