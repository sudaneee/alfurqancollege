from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from . import audit
from .bulk import get_importer
from .excel import ExcelError, build_workbook, read_rows, workbook_response
from .forms import SiteSettingsForm
from .models import AuditLog, ImportBatch, SiteSettings
from .permissions import has_perm, staff_required


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@staff_required()
def dashboard(request):
    from apps.academics.models import AcademicSession, CourseAllocation, Department, Semester
    from apps.admissions.models import Application, ApplicationPeriod
    from apps.bursary.models import Invoice, Payment
    from apps.registration.models import CourseRegistration
    from apps.results.models import ResultSheet
    from apps.students.models import Student

    user = request.user
    semester = Semester.current()
    session = AcademicSession.current()
    ctx = {"semester": semester, "session": session, "today": timezone.localdate()}
    site = SiteSettings.load()
    ctx["needs_content_review"] = has_perm(user, "manage_settings") and not site.content_reviewed

    if has_perm(user, "view_students"):
        enrolled = Student.objects.filter(status__counts_as_enrolled=True)
        ctx["student_count"] = enrolled.count()
        ctx["students_by_programme"] = list(
            enrolled.values("programme__name").annotate(n=Count("id")).order_by("-n"))
        top = max([r["n"] for r in ctx["students_by_programme"]] or [1])
        for r in ctx["students_by_programme"]:
            r["pct"] = round(r["n"] * 100 / top)

    if has_perm(user, "view_applications"):
        period = ApplicationPeriod.current() or ApplicationPeriod.objects.first()
        apps = Application.objects.filter(period=period) if period else Application.objects.none()
        ctx["period"] = period
        ctx["app_stats"] = {
            "total": apps.exclude(status=Application.DRAFT).count(),
            "pending": apps.filter(status__in=[Application.SUBMITTED, Application.UNDER_REVIEW]).count(),
            "admitted": apps.filter(status=Application.ADMITTED).count(),
            "accepted": apps.filter(offer_status=Application.OFFER_ACCEPTED).count(),
        }
        ctx["recent_applications"] = apps.exclude(status=Application.DRAFT).select_related("first_choice").order_by("-submitted_at")[:6]

    if has_perm(user, "view_finance"):
        paid = Payment.objects.filter(status=Payment.SUCCESSFUL)
        ctx["fin"] = {
            "today": paid.filter(paid_at__date=timezone.localdate()).aggregate(t=Sum("amount"))["t"] or 0,
            "session": paid.filter(invoice__session=session).aggregate(t=Sum("amount"))["t"] or 0 if session else 0,
            "pending": Payment.objects.filter(status=Payment.PENDING).exclude(method="online").count(),
            "outstanding": sum(i.balance for i in Invoice.objects.filter(status__in=[Invoice.UNPAID, Invoice.PART_PAID])),
        }
        ctx["recent_payments"] = paid.select_related("invoice__student", "invoice__application").order_by("-paid_at")[:6]

    if has_perm(user, "view_registrations") and semester:
        regs = CourseRegistration.objects.filter(semester=semester)
        ctx["reg_stats"] = {
            "total": regs.exclude(status=CourseRegistration.DRAFT).count(),
            "awaiting": regs.filter(status=CourseRegistration.SUBMITTED).count(),
            "approved": regs.filter(status=CourseRegistration.APPROVED).count(),
        }

    if has_perm(user, "approve_results") or has_perm(user, "publish_results") or has_perm(user, "manage_all_results"):
        sheets = ResultSheet.objects.all()
        ctx["result_stats"] = {
            "submitted": sheets.filter(status=ResultSheet.SUBMITTED).count(),
            "to_approve": sheets.filter(status=ResultSheet.HOD_APPROVED).count(),
            "to_publish": sheets.filter(status=ResultSheet.APPROVED).count(),
            "published": sheets.filter(status=ResultSheet.PUBLISHED).count(),
        }

    if has_perm(user, "review_results"):
        depts = Department.objects.filter(hod=user)
        if depts:
            ctx["hod_departments"] = depts
            ctx["hod_awaiting"] = ResultSheet.objects.filter(status=ResultSheet.SUBMITTED, course__programme__department__in=depts).select_related("course", "semester")
            ctx["hod_students"] = Student.objects.filter(programme__department__in=depts, status__counts_as_enrolled=True).count()
            ctx["hod_lecturers"] = CourseAllocation.objects.filter(course__programme__department__in=depts, semester=semester).values("lecturer").distinct().count() if semester else 0

    if has_perm(user, "upload_results") and semester:
        allocs = CourseAllocation.objects.filter(lecturer=user, semester=semester).select_related("course__programme")
        sheets = {s.course_id: s for s in ResultSheet.objects.filter(semester=semester, course__in=[a.course for a in allocs])}
        from apps.registration.services import registered_items
        if allocs or not has_perm(user, "manage_all_results"):
            ctx["my_courses"] = [{"alloc": a, "sheet": sheets.get(a.course_id), "students": registered_items(a.course, semester).count()} for a in allocs]

    if has_perm(user, "view_audit_log"):
        ctx["recent_activity"] = AuditLog.objects.select_related("actor")[:8]
    return render(request, "core/dashboard.html", ctx)


@staff_required("manage_users", "manage_roles", "manage_settings", "view_audit_log", "manage_notifications")
def system(request):
    return render(request, "core/system.html")


@staff_required("manage_settings")
def settings_edit(request):
    obj = SiteSettings.load()
    before = audit.snapshot(obj)
    form = SiteSettingsForm(request.POST or None, request.FILES or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        audit.log(request.user, "settings_updated", saved, changes=audit.diff(before, audit.snapshot(saved)))
        messages.success(request, "Institutional settings saved.")
        return redirect("core:settings")
    return render(request, "core/settings.html", {"form": form})


@staff_required("view_audit_log")
def audit_log(request):
    qs = AuditLog.objects.select_related("actor", "on_behalf_of")
    q = request.GET.get("q", "").strip()
    module = request.GET.get("module", "")
    if q:
        qs = qs.filter(Q(object_repr__icontains=q) | Q(action__icontains=q) | Q(actor__username__icontains=q)
                       | Q(actor__first_name__icontains=q) | Q(actor__last_name__icontains=q) | Q(note__icontains=q))
    if module:
        qs = qs.filter(module=module)
    if request.GET.get("assisted"):
        qs = qs.filter(on_behalf_of__isnull=False)
    modules = AuditLog.objects.values_list("module", flat=True).distinct().order_by("module")
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    return render(request, "core/audit_log.html", {"page": page, "q": q, "module": module, "modules": modules})


@staff_required()
def search(request):
    from apps.admissions.models import Application
    from apps.bursary.models import Invoice
    from apps.students.models import Student

    q = request.GET.get("q", "").strip()
    results = {}
    if len(q) >= 2:
        if has_perm(request.user, "view_students"):
            results["students"] = Student.objects.filter(
                Q(matric_number__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)
                | Q(phone__icontains=q) | Q(email__icontains=q)).select_related("programme", "status")[:20]
        if has_perm(request.user, "view_applications"):
            results["applications"] = Application.objects.filter(
                Q(application_number__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)
                | Q(phone__icontains=q) | Q(email__icontains=q)).select_related("first_choice")[:20]
        if has_perm(request.user, "view_finance"):
            results["invoices"] = Invoice.objects.filter(Q(number__icontains=q) | Q(payments__reference__icontains=q)).distinct()[:20]
    return render(request, "core/search.html", {"q": q, "results": results})


# ---------------------------------------------------------------------------
# Bulk operations (generic)
# ---------------------------------------------------------------------------
def _importer_or_404(kind, request):
    importer = get_importer(kind, request.user)
    if importer is None:
        from django.http import Http404
        raise Http404("Unknown bulk operation")
    return importer


@staff_required()
def bulk_home(request, kind):
    importer = _importer_or_404(kind, request)
    context = importer.clean_context(request.GET, request.user)  # upload form posts back to the same URL
    importer.check_access(request.user, context)
    needs_reason = False
    if kind == "scores":
        from apps.results.models import ResultSheet
        sheet = ResultSheet.objects.filter(pk=context.get("sheet")).first()
        needs_reason = bool(sheet and not sheet.is_editable)
    if request.method == "POST":
        f = request.FILES.get("file")
        if needs_reason:
            context["reason"] = request.POST.get("reason", "").strip()
            if not context["reason"]:
                messages.error(request, "Please give a reason for changing a locked result.")
                return redirect(request.get_full_path())
        if not f:
            messages.error(request, "Choose an Excel file to upload.")
        else:
            try:
                _, raw = read_rows(f)
            except ExcelError as exc:
                messages.error(request, str(exc))
            else:
                if not raw:
                    messages.error(request, "The file has no data rows.")
                else:
                    rows = importer.run_validation(raw, context)
                    batch = ImportBatch.objects.create(kind=kind, context=context, file_name=f.name[:255], rows=rows,
                                                       created_by=request.user)
                    return redirect("core:bulk_preview", batch.pk)
    batches = ImportBatch.objects.filter(kind=kind, created_by=request.user)[:8]
    return render(request, "core/bulk_home.html", {"importer": importer, "batches": batches,
                                                   "context_label": importer.context_label(context),
                                                   "needs_reason": needs_reason})


@staff_required()
def bulk_template(request, kind):
    importer = _importer_or_404(kind, request)
    context = importer.clean_context(request.GET, request.user)
    importer.check_access(request.user, context)
    choices = {i: c.choices for i, c in enumerate(importer.columns) if c.choices}
    wb = build_workbook(importer.headers(), importer.template_rows(context), title=importer.title[:31],
                        notes=importer.notes(context), choices=choices)
    return workbook_response(wb, importer.template_filename(context))


def _batch_for(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk)
    if batch.created_by_id != request.user.id and not request.user.is_superuser:
        raise PermissionDenied("This upload belongs to another user.")
    importer = _importer_or_404(batch.kind, request)
    importer.check_access(request.user, batch.context)
    return batch, importer


@staff_required()
def bulk_preview(request, pk):
    batch, importer = _batch_for(request, pk)
    show = request.GET.get("show", "all")
    rows = [r for r in batch.rows if r.get("errors")] if show == "errors" else batch.rows
    from urllib.parse import urlencode
    ctx = {
        "batch": batch, "importer": importer, "rows": rows, "show": show,
        "failed_count": batch.error_count,
        "to_apply": sum(1 for r in batch.rows if not r.get("errors") and r.get("action") != "skip"),
        "skip_count": sum(1 for r in batch.rows if not r.get("errors") and r.get("action") == "skip"),
        "context_qs": urlencode({k: v for k, v in batch.context.items() if k in importer.context_keys}),
    }
    return render(request, "core/bulk_preview.html", ctx)


@staff_required()
def bulk_confirm(request, pk):
    batch, importer = _batch_for(request, pk)
    if request.method != "POST":
        return redirect("core:bulk_preview", pk)
    if batch.status != ImportBatch.STATUS_PREVIEW:
        messages.warning(request, "This upload has already been processed.")
        return redirect("core:bulk_preview", pk)
    summary = importer.apply(batch, request.user)
    level = messages.success if not summary["failed"] else messages.warning
    level(request, f"{summary['applied']} row(s) applied, {summary['skipped']} unchanged, {summary['failed']} failed.")
    return redirect("core:bulk_preview", pk)


@staff_required()
def bulk_cancel(request, pk):
    batch, _ = _batch_for(request, pk)
    if request.method == "POST" and batch.status == ImportBatch.STATUS_PREVIEW:
        batch.status = ImportBatch.STATUS_CANCELLED
        batch.save(update_fields=["status"])
        messages.info(request, "Upload cancelled. Nothing was saved.")
    return redirect("core:bulk_home", batch.kind)


@staff_required()
def bulk_failed(request, pk):
    batch, importer = _batch_for(request, pk)
    headers = importer.headers() + ["Errors"]
    rows = [[r["data"].get(c.key, "") for c in importer.columns] + ["; ".join(r["errors"])]
            for r in batch.rows if r.get("errors")]
    wb = build_workbook(headers, rows, title="Failed rows")
    return workbook_response(wb, f"failed_rows_{batch.kind}_{batch.pk}.xlsx")


def error_403(request, exception=None):
    return render(request, "errors/403.html", {"message": str(exception or "")}, status=403)


def error_404(request, exception=None):
    return render(request, "errors/404.html", status=404)


def error_500(request):
    return render(request, "errors/500.html", status=500)
