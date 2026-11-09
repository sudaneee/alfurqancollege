"""Institutional reports. Each report returns a title, column headers and rows,
so every report is automatically viewable on screen and exportable to Excel/PDF."""
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone

from apps.academics.models import AcademicSession, Programme, Semester
from apps.admissions.models import Application, ApplicationPeriod
from apps.bursary.models import FeeCategory, Invoice, InvoiceLine, Payment
from apps.core import audit
from apps.core.excel import export_response
from apps.core.pdf import render_pdf
from apps.core.permissions import has_perm, staff_required
from apps.registration.models import CourseRegistration
from apps.results.models import ResultSheet, Score
from apps.students.models import Student

REPORTS = {}


def report(key, title, description, icon, group, perm="view_reports", filters=()):
    def deco(fn):
        REPORTS[key] = {"key": key, "title": title, "description": description, "icon": icon, "group": group,
                        "fn": fn, "perm": perm, "filters": filters}
        return fn
    return deco


def _session(request):
    return AcademicSession.objects.filter(pk=request.GET.get("session")).first() or AcademicSession.current()


def _programme(request):
    return Programme.objects.filter(pk=request.GET.get("programme")).first()


@report("applications", "Applicants & admission statistics", "Applications, admissions and acceptances by programme.",
        "bi-person-plus", "Admissions", filters=("period",))
def r_applications(request):
    period = ApplicationPeriod.objects.filter(pk=request.GET.get("period")).first() or ApplicationPeriod.current() or ApplicationPeriod.objects.first()
    qs = Application.objects.filter(period=period).exclude(status=Application.DRAFT) if period else Application.objects.none()
    rows = []
    for p in Programme.objects.all():
        sub = qs.filter(first_choice=p)
        t = sub.count()
        adm = qs.filter(admitted_programme=p, status=Application.ADMITTED).count()
        acc = qs.filter(admitted_programme=p, offer_status=Application.OFFER_ACCEPTED).count()
        rows.append([p.name, t, sub.filter(status__in=[Application.SUBMITTED, Application.UNDER_REVIEW]).count(), adm, acc,
                     sub.filter(status=Application.NOT_ADMITTED).count(), f"{round(adm * 100 / t) if t else 0}%"])
    totals = ["Total"] + [sum(r[i] for r in rows) for i in range(1, 6)] + [""]
    return {"subtitle": str(period or ""), "headers": ["Programme", "Applications", "Pending", "Admitted", "Accepted", "Not admitted", "Admission rate"],
            "rows": rows, "totals": totals}


@report("population", "Student population", "Enrolled students by programme and level, with gender split.", "bi-people", "Students")
def r_population(request):
    rows = []
    enrolled = Student.objects.filter(status__counts_as_enrolled=True)
    for p in Programme.objects.all():
        for y in range(1, p.duration_years + 1):
            sub = enrolled.filter(programme=p, current_year=y)
            rows.append([p.name, p.level_name(y), sub.filter(gender="M").count(), sub.filter(gender="F").count(), sub.count()])
    totals = ["Total", "", sum(r[2] for r in rows), sum(r[3] for r in rows), sum(r[4] for r in rows)]
    return {"headers": ["Programme", "Level", "Male", "Female", "Total"], "rows": rows, "totals": totals}


@report("status", "Students by status", "All student records grouped by status and programme.", "bi-toggles", "Students")
def r_status(request):
    data = Student.objects.values("programme__name", "status__name").annotate(n=Count("id")).order_by("programme__name", "status__name")
    rows = [[d["programme__name"], d["status__name"], d["n"]] for d in data]
    return {"headers": ["Programme", "Status", "Students"], "rows": rows, "totals": ["Total", "", sum(r[2] for r in rows)]}


@report("registrations", "Course registration report", "Registration status by programme and level for a semester.",
        "bi-journal-check", "Academics", filters=("semester",))
def r_registrations(request):
    sem = Semester.objects.filter(pk=request.GET.get("semester")).first() or Semester.current()
    qs = CourseRegistration.objects.filter(semester=sem) if sem else CourseRegistration.objects.none()
    data = (qs.values("student__programme__name", "year_of_study")
            .annotate(total=Count("id"), approved=Count("id", filter=Q(status="approved")),
                      submitted=Count("id", filter=Q(status="submitted")), draft=Count("id", filter=Q(status="draft")))
            .order_by("student__programme__name", "year_of_study"))
    rows = []
    for d in data:
        enrolled = Student.objects.filter(programme__name=d["student__programme__name"], current_year=d["year_of_study"],
                                          status__counts_as_enrolled=True).count()
        rows.append([d["student__programme__name"], d["year_of_study"], enrolled, d["approved"], d["submitted"], d["draft"],
                     max(0, enrolled - d["approved"] - d["submitted"])])
    return {"subtitle": str(sem or ""), "headers": ["Programme", "Year", "Enrolled", "Approved", "Awaiting approval", "Draft", "Not completed"],
            "rows": rows}


@report("results", "Course result analysis", "Pass rates, averages and status for each course result.", "bi-clipboard-data",
        "Academics", filters=("semester", "programme"))
def r_results(request):
    sem = Semester.objects.filter(pk=request.GET.get("semester")).first() or Semester.current()
    qs = ResultSheet.objects.filter(semester=sem).select_related("course__programme__grading_scheme") if sem else ResultSheet.objects.none()
    prog = _programme(request)
    if prog:
        qs = qs.filter(course__programme=prog)
    rows = []
    for sh in qs.order_by("course__programme__code", "course__code"):
        scores = [s for s in sh.scores.all() if s.total is not None]
        passed = sum(1 for s in scores if s.total >= sh.scheme.pass_mark)
        avg = round(sum(float(s.total) for s in scores) / len(scores), 1) if scores else ""
        rows.append([sh.course.code, sh.course.title, sh.course.programme.code, len(scores), passed, len(scores) - passed,
                     f"{round(passed * 100 / len(scores)) if scores else 0}%", avg, sh.get_status_display()])
    return {"subtitle": str(sem or ""), "headers": ["Code", "Course", "Prog.", "Students", "Passed", "Failed", "Pass rate", "Average", "Status"], "rows": rows}


@report("cgpa", "GPA / CGPA & classification", "Cumulative GPA and projected diploma class for students.", "bi-graph-up",
        "Academics", perm="generate_transcripts", filters=("programme", "year"))
def r_cgpa(request):
    from apps.results.services import cgpa_for

    qs = Student.objects.filter(status__counts_as_enrolled=True).select_related("programme__grading_scheme")
    prog = _programme(request)
    if prog:
        qs = qs.filter(programme=prog)
    if request.GET.get("year"):
        qs = qs.filter(current_year=request.GET["year"])
    rows = []
    for s in qs.order_by("programme__code", "matric_number"):
        c = cgpa_for(s)
        rows.append([s.matric_number, s.full_name, s.programme.code, s.level_label, c if c is not None else "",
                     s.programme.grading_scheme.classify(c) if c is not None else ""])
    rows.sort(key=lambda r: -(r[4] or 0))
    return {"headers": ["Matric", "Name", "Prog.", "Level", "CGPA", "Class"], "rows": rows}


@report("collections", "Payment collection report", "Successful payments by fee category and method within a date range.",
        "bi-cash-stack", "Finance", perm="view_finance", filters=("from", "to"))
def r_collections(request):
    qs = Payment.objects.filter(status=Payment.SUCCESSFUL)
    d1, d2 = request.GET.get("from"), request.GET.get("to")
    if d1:
        qs = qs.filter(paid_at__date__gte=d1)
    if d2:
        qs = qs.filter(paid_at__date__lte=d2)
    rows = []
    for m, label in Payment.METHOD_CHOICES:
        sub = qs.filter(method=m)
        n = sub.count()
        if n:
            rows.append([label, n, sub.aggregate(t=Sum("amount"))["t"] or Decimal(0)])
    total = qs.aggregate(t=Sum("amount"))["t"] or Decimal(0)
    # allocation by category: share of each invoice's lines (proportional)
    cat_rows = []
    for cat in FeeCategory.objects.all():
        amt = Decimal(0)
        for p in qs.select_related("invoice"):
            gross = p.invoice.gross_amount or Decimal(0)
            if gross:
                line_total = sum((l.amount for l in p.invoice.lines.all() if l.category_id == cat.id), Decimal(0))
                amt += (p.amount * line_total / gross)
        if amt:
            cat_rows.append([f"Category: {cat.name}", "", amt.quantize(Decimal("0.01"))])
    return {"subtitle": f"{d1 or 'start'} to {d2 or timezone.localdate()}", "headers": ["Breakdown", "Payments", "Amount (₦)"],
            "rows": rows + cat_rows, "totals": ["Total collected", qs.count(), total], "money_cols": [2]}


@report("outstanding", "Outstanding payments", "Students with unpaid or partly paid invoices.", "bi-exclamation-circle",
        "Finance", perm="view_finance", filters=("session", "programme"))
def r_outstanding(request):
    qs = Invoice.objects.filter(status__in=[Invoice.UNPAID, Invoice.PART_PAID], student__isnull=False).select_related("student__programme", "session")
    sess, prog = request.GET.get("session"), _programme(request)
    if sess:
        qs = qs.filter(session_id=sess)
    if prog:
        qs = qs.filter(student__programme=prog)
    rows = [[i.student.matric_number, i.student.full_name, i.student.programme.code, i.student.phone, i.number, i.session,
             i.net_amount, i.amount_paid, i.balance] for i in qs.order_by("student__programme__code", "student__matric_number")]
    return {"headers": ["Matric", "Name", "Prog.", "Phone", "Invoice", "Session", "Net (₦)", "Paid (₦)", "Balance (₦)"], "rows": rows,
            "totals": ["Total", "", "", "", "", "", sum(r[6] for r in rows), sum(r[7] for r in rows), sum(r[8] for r in rows)],
            "money_cols": [6, 7, 8]}


@report("staff", "Staff report", "Staff accounts, roles, departments and course allocations this semester.", "bi-person-badge",
        "Administration", perm="view_staff")
def r_staff(request):
    from apps.academics.models import CourseAllocation
    from apps.accounts.models import User

    sem = Semester.current()
    rows = []
    for u in User.objects.filter(user_type="staff").select_related("staff_profile__department").prefetch_related("groups").order_by("first_name"):
        prof = getattr(u, "staff_profile", None)
        n = CourseAllocation.objects.filter(lecturer=u, semester=sem).count() if sem else 0
        rows.append([prof.staff_id if prof else "", u.get_full_name(), u.email, prof.department if prof and prof.department else "",
                     prof.designation if prof else "", ", ".join(g.name for g in u.groups.all()) or ("Super Administrator" if u.is_superuser else ""),
                     n, "Active" if u.is_active else "Deactivated"])
    return {"subtitle": str(sem or ""), "headers": ["Staff ID", "Name", "E-mail", "Department", "Designation", "Roles", "Courses", "Status"], "rows": rows}


@staff_required("view_reports", "view_finance", "generate_transcripts", "view_staff")
def index(request):
    groups = {}
    for r in REPORTS.values():
        if has_perm(request.user, r["perm"]):
            groups.setdefault(r["group"], []).append(r)
    return render(request, "reports/index.html", {"groups": groups})


@staff_required()
def view_report(request, key):
    r = REPORTS.get(key)
    if r is None:
        raise Http404
    if not has_perm(request.user, r["perm"]):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    data = r["fn"](request)
    fmt = request.GET.get("export")
    if fmt in ("xlsx", "pdf"):
        audit.log(request.user, f"report_exported_{fmt}", None, module="reports", object_repr=r["title"])
    if fmt == "xlsx":
        rows = data["rows"] + ([data["totals"]] if data.get("totals") else [])
        return export_response(f"{key}_report.xlsx", data["headers"], rows, r["title"][:31])
    ctx = {"r": r, "data": data, "generated": timezone.now(), "sessions": AcademicSession.objects.all(),
           "programmes": Programme.objects.all(), "semesters": Semester.objects.select_related("session")[:10],
           "periods": ApplicationPeriod.objects.all()}
    if fmt == "pdf":
        return render_pdf("pdf/report.html", ctx, f"{key}_report.pdf", request)
    return render(request, "reports/report.html", ctx)


@staff_required("view_finance")
def outstanding(request):
    return view_report(request, "outstanding")
