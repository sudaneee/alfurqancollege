from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.academics.models import Course, Programme, Semester
from apps.core.excel import export_response
from apps.core.pdf import render_pdf
from apps.core.permissions import has_perm, staff_required, student_required
from apps.students.models import Student

from . import services
from .models import CourseRegistration


def _registration_page(request, student, semester, mode):
    """Shared course-registration screen for students and for staff acting on their behalf."""
    staff = mode == "staff"
    reg = CourseRegistration.objects.filter(student=student, semester=semester).first() if semester else None
    if request.method == "POST" and semester:
        action = request.POST.get("action")
        try:
            if action == "add":
                ids = request.POST.getlist("courses")
                courses = list(Course.objects.filter(pk__in=ids))
                if not courses:
                    raise ValidationError("Select at least one course to add.")
                reg = services.add_courses(student, semester, courses, request.user)
                messages.success(request, f"{len(courses)} course(s) added.")
            elif action == "drop" and reg:
                course = get_object_or_404(Course, pk=request.POST.get("course"))
                services.drop_course(reg, course, request.user, request.POST.get("reason", ""))
                messages.success(request, f"{course.code} dropped.")
            elif action == "submit" and reg:
                reg = services.submit_registration(reg, request.user)
                messages.success(request, "Registration approved." if reg.status == CourseRegistration.APPROVED
                                 else "Registration submitted for approval.")
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        return redirect(request.get_full_path())
    available, carry_ids = services.available_courses(student, semester) if semester else ([], set())
    registered_ids = set(reg.items.values_list("course_id", flat=True)) if reg else set()
    window_open = semester.registration_is_open() if semester else False
    add_drop_open = semester.add_drop_is_open() if semester else False
    can_edit = bool(semester) and (
        staff or (student.status.can_register_courses and (
            (reg is None or reg.status in (CourseRegistration.DRAFT, CourseRegistration.REJECTED)) and window_open
            or reg is not None and reg.status == CourseRegistration.APPROVED and add_drop_open)))
    ctx = {
        "s": student, "semester": semester, "reg": reg, "staff": staff, "can_edit": can_edit, "today": timezone.localdate(),
        "items": reg.items.select_related("course", "added_by") if reg else [],
        "available": [c for c in available if c.id not in registered_ids], "carry_ids": carry_ids,
        "window_open": window_open, "add_drop_open": add_drop_open,
        "override": services.can_override(request.user),
        "events": reg.events.select_related("course", "actor")[:20] if reg else [],
        "history": student.registrations.select_related("semester__session").exclude(pk=reg.pk if reg else None),
        "semesters": Semester.objects.select_related("session")[:8] if staff else None,
        "base_template": "staff/base.html" if staff else "students/portal/base.html",
    }
    return render(request, "registration/register.html", ctx)


@student_required
def portal_courses(request):
    return _registration_page(request, request.student, Semester.current(), "portal")


@staff_required("manage_registrations", "view_registrations")
def staff_student(request, pk):
    student = get_object_or_404(Student.objects.select_related("programme", "status"), pk=pk)
    if request.method == "POST" and not has_perm(request.user, "manage_registrations"):
        raise PermissionDenied("You can view but not change registrations.")
    sid = request.GET.get("semester")
    semester = Semester.objects.filter(pk=sid).first() if sid else Semester.current()
    return _registration_page(request, student, semester, "staff")


@staff_required("view_registrations", "manage_registrations", "approve_registrations")
def staff_list(request):
    semester = Semester.objects.filter(pk=request.GET.get("semester")).first() if request.GET.get("semester") else Semester.current()
    qs = CourseRegistration.objects.select_related("student__programme", "semester__session", "reviewed_by").annotate(
        n=Count("items"), units=Sum("items__course__credit_units"))
    if semester:
        qs = qs.filter(semester=semester)
    for key, field in (("status", "status"), ("programme", "student__programme_id"), ("year", "year_of_study")):
        if request.GET.get(key):
            qs = qs.filter(**{field: request.GET[key]})
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(student__matric_number__icontains=q) | Q(student__first_name__icontains=q) | Q(student__last_name__icontains=q))
    if request.method == "POST":
        if not has_perm(request.user, "approve_registrations"):
            raise PermissionDenied
        approve = request.POST.get("decision") == "approve"
        ok = 0
        for reg in CourseRegistration.objects.filter(pk__in=request.POST.getlist("selected"), status=CourseRegistration.SUBMITTED):
            try:
                services.review_registration(reg, approve, request.user, request.POST.get("note", ""))
                ok += 1
            except ValidationError:
                pass
        messages.success(request, f"{ok} registration(s) {'approved' if approve else 'returned'}.")
        return redirect(request.get_full_path())
    if request.GET.get("export") == "xlsx":
        rows = []
        for r in qs.prefetch_related("items__course"):
            rows.append([r.student.matric_number, r.student.full_name, r.student.programme.name, r.student.programme.level_name(r.year_of_study),
                         str(r.semester), r.get_status_display(), r.units or 0, ", ".join(i.course.code for i in r.items.all())])
        return export_response("course_registrations.xlsx", ["Matric", "Name", "Programme", "Level", "Semester", "Status", "Units", "Courses"], rows)
    stats = dict(qs.values_list("status").annotate(c=Count("id", distinct=True)).values_list("status", "c"))
    page = Paginator(qs.order_by("student__matric_number"), 40).get_page(request.GET.get("page"))
    return render(request, "registration/staff_list.html", {
        "page": page, "semester": semester, "semesters": Semester.objects.select_related("session")[:10],
        "programmes": Programme.objects.all(), "statuses": CourseRegistration.STATUS_CHOICES, "stats": stats, "q": q})


@staff_required("approve_registrations")
@require_POST
def staff_review(request, pk):
    reg = get_object_or_404(CourseRegistration, pk=pk)
    try:
        services.review_registration(reg, request.POST.get("decision") == "approve", request.user, request.POST.get("note", ""))
        messages.success(request, "Registration updated.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect(request.POST.get("next") or f"/staff/registration/student/{reg.student_id}/?semester={reg.semester_id}")


def slip(request, pk):
    reg = get_object_or_404(CourseRegistration.objects.select_related("student__programme__department", "semester__session"), pk=pk)
    user = request.user
    if not user.is_authenticated:
        return redirect("accounts:student_login")
    if reg.student.user_id != user.id and not has_perm(user, "view_registrations"):
        raise PermissionDenied
    if reg.status == CourseRegistration.DRAFT:
        messages.error(request, "Submit the registration before printing the slip.")
        return redirect("registration:portal_courses")
    return render_pdf("pdf/registration_slip.html", {"reg": reg, "items": reg.items.select_related("course")},
                      f"course_registration_{reg.student.matric_number.replace('/', '-')}.pdf", request)
