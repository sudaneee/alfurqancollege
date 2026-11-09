from django.contrib import messages
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core import audit
from apps.core.crud import Crud
from apps.core.excel import export_response
from apps.core.permissions import staff_required

from . import forms
from .models import (AcademicDocument, AcademicSession, CalendarEvent, Course, CourseAllocation, Department,
                     PracticalRequirement, Programme, Semester)

SECTION = "Academic setup"
PERM = ("manage_academics",)


def _course_filter(qs, request):
    prog = request.GET.get("programme")
    if prog:
        qs = qs.filter(programme_id=prog)
    return qs.select_related("programme")


CRUDS = [
    Crud("department", Department, forms.DepartmentForm, PERM, "Departments", "Department", section=SECTION,
         list_display=[("Department", "name"), ("Code", "code"), ("Head of Department", "hod"), ("Active", "is_active")],
         search_fields=["name", "code"]),
    Crud("programme", Programme, forms.ProgrammeForm, PERM, "Programmes", "Programme", section=SECTION,
         description="Programme structure, duration, assessment weighting, grading system and public information.",
         list_display=[("Programme", "name"), ("Code", "code"), ("Duration (years)", "duration_years"),
                       ("Grading", "grading_scheme"), ("CA/Exam", "assessment_split"), ("Published", "is_published")],
         search_fields=["name", "code"], detail_url=lambda o: f"/staff/academics/programmes/{o.pk}/curriculum/"),
    Crud("session", AcademicSession, forms.SessionForm, PERM, "Academic sessions", "Session", section=SECTION,
         list_display=[("Session", "name"), ("Starts", "start_date"), ("Ends", "end_date"), ("Current", "is_current")]),
    Crud("semester", Semester, forms.SemesterForm, PERM, "Semesters", "Semester", section=SECTION,
         description="Mark one semester as current. Registration dates control when students can register online.",
         list_display=[("Semester", "__str__"), ("Registration opens", "registration_opens"),
                       ("Registration closes", "registration_closes"), ("Add/drop closes", "add_drop_closes"),
                       ("Current", "is_current")]),
    Crud("course", Course, forms.CourseForm, PERM, "Courses", "Course", section=SECTION,
         list_display=[("Code", "code"), ("Title", "title"), ("Programme", "programme__code"), ("Level", "slot_label"),
                       ("Units", "credit_units"), ("Type", "course_type"), ("Active", "is_active")],
         search_fields=["code", "title", "programme__name"], ordering=("programme", "year", "term", "code"),
         queryset_hook=_course_filter),
    Crud("practical", PracticalRequirement, forms.PracticalForm, PERM, "Practical requirements", "Practical requirement",
         section=SECTION, description="SIWES, supervised clinical / community-based experience, projects and licensing examinations.",
         list_display=[("Title", "title"), ("Programme", "programme__code"), ("Type", "kind"), ("Timing", "timing"),
                       ("Duration", "duration")]),
    Crud("calendar", CalendarEvent, forms.CalendarEventForm, PERM, "Academic calendar", "Calendar event", section=SECTION,
         list_display=[("Event", "title"), ("Session", "session"), ("Category", "category"), ("Starts", "start_date"),
                       ("Ends", "end_date"), ("Public", "is_public")], search_fields=["title"]),
    Crud("document", AcademicDocument, forms.AcademicDocumentForm, PERM, "Academic documents", "Document", section=SECTION,
         description="Curricula, handbooks and timetables students can download from their portal.",
         list_display=[("Title", "title"), ("Programme", "programme"), ("Public", "is_public"), ("Uploaded", "uploaded_at")]),
]

@staff_required("manage_academics", "allocate_courses")
def overview(request):
    programmes = Programme.objects.select_related("department", "grading_scheme").annotate(
        n_courses=Count("courses", distinct=True), units=Sum("courses__credit_units"))
    ctx = {
        "programmes": programmes,
        "semester": Semester.current(),
        "session": AcademicSession.current(),
        "counts": {"departments": Department.objects.count(), "courses": Course.objects.count(),
                   "sessions": AcademicSession.objects.count(), "allocations": CourseAllocation.objects.filter(semester=Semester.current()).count()},
    }
    return render(request, "academics/overview.html", ctx)


@staff_required("manage_academics", "allocate_courses", "view_students")
def curriculum(request, pk):
    programme = get_object_or_404(Programme.objects.select_related("department", "grading_scheme"), pk=pk)
    courses = programme.courses.prefetch_related("prerequisites").order_by("year", "term", "code")
    slots = []
    for year in range(1, programme.duration_years + 1):
        for term in (1, 2):
            items = [c for c in courses if c.year == year and c.term == term]
            slots.append({"year": year, "term": term, "label": f"{programme.level_name(year)} — {'First' if term == 1 else 'Second'} Semester",
                          "courses": items, "units": sum(c.credit_units for c in items)})
    if request.GET.get("export") == "xlsx":
        rows = [[c.code, c.title, c.credit_units, c.lecture_hours, c.tutorial_hours, c.practical_hours, programme.level_name(c.year),
                 c.get_term_display(), c.get_course_type_display(), ", ".join(p.code for p in c.prerequisites.all())] for c in courses]
        return export_response(f"curriculum_{programme.code}.xlsx", ["Code", "Title", "Units", "L", "T", "P", "Level", "Semester", "Type", "Prerequisites"], rows, programme.code)
    return render(request, "academics/curriculum.html", {"programme": programme, "slots": slots,
                                                         "practicals": programme.practical_requirements.all(),
                                                         "bands": programme.grading_scheme.bands.all(),
                                                         "classes": programme.grading_scheme.classifications.all()})


@staff_required("allocate_courses", "manage_academics")
def allocations(request):
    semester_id = request.GET.get("semester") or (Semester.current().pk if Semester.current() else None)
    semester = Semester.objects.filter(pk=semester_id).first()
    form = forms.AllocationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        a = CourseAllocation.objects.create(course=d["course"], semester=d["semester"], lecturer=d["lecturer"],
                                            is_coordinator=d["is_coordinator"], allocated_by=request.user)
        audit.log(request.user, "course_allocated", a)
        from apps.notifications.services import notify
        notify(d["lecturer"], "course_allocated", {"course": f"{d['course'].code} {d['course'].title}", "semester": str(d["semester"])},
               link="/staff/results/my-courses/")
        messages.success(request, f"{d['course'].code} allocated to {d['lecturer']}.")
        return redirect(f"{request.path}?semester={d['semester'].pk}")
    qs = CourseAllocation.objects.select_related("course__programme", "lecturer", "semester__session")
    if semester:
        qs = qs.filter(semester=semester)
    prog = request.GET.get("programme")
    if prog:
        qs = qs.filter(course__programme_id=prog)
    unallocated = []
    if semester:
        allocated_ids = set(qs.values_list("course_id", flat=True)) if not prog else set(
            CourseAllocation.objects.filter(semester=semester).values_list("course_id", flat=True))
        unallocated = Course.objects.filter(term=semester.term, is_active=True).exclude(pk__in=allocated_ids).select_related("programme")
        if prog:
            unallocated = unallocated.filter(programme_id=prog)
    return render(request, "academics/allocations.html", {
        "form": form, "allocations": qs.order_by("course__programme__code", "course__code"), "semester": semester,
        "semesters": Semester.objects.select_related("session")[:12], "programmes": Programme.objects.all(), "prog": prog,
        "unallocated": unallocated,
    })


@staff_required("allocate_courses", "manage_academics")
@require_POST
def allocation_delete(request, pk):
    a = get_object_or_404(CourseAllocation, pk=pk)
    audit.log(request.user, "course_unallocated", a)
    sem = a.semester_id
    a.delete()
    messages.success(request, "Allocation removed.")
    return redirect(f"/staff/academics/allocations/?semester={sem}")
