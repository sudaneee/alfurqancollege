from collections import Counter
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.forms import inlineformset_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.academics.models import Course, CourseAllocation, Programme, Semester
from apps.core.crud import Crud
from apps.core.excel import export_response
from apps.core.forms import StyledModelForm
from apps.core.pdf import render_pdf
from apps.core.permissions import has_any, has_perm, staff_required, student_required
from apps.registration.services import registered_items
from apps.students.models import Student

from . import services
from .models import ClassificationBand, GradeBand, GradingScheme, ResultSheet


# ---------------------------------------------------------------------------
# Grading configuration
# ---------------------------------------------------------------------------
class SchemeForm(StyledModelForm):
    class Meta:
        model = GradingScheme
        fields = ["name", "source", "pass_mark", "max_points", "cgpa_policy", "description"]


class BandForm(StyledModelForm):
    class Meta:
        model = GradeBand
        fields = ["min_score", "max_score", "letter", "points", "remark"]


class ClassForm(StyledModelForm):
    class Meta:
        model = ClassificationBand
        fields = ["min_cgpa", "max_cgpa", "label"]


class BaseBandFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        ranges = []
        for f in self.forms:
            if not f.cleaned_data or f.cleaned_data.get("DELETE"):
                continue
            lo, hi = f.cleaned_data.get("min_score"), f.cleaned_data.get("max_score")
            if lo is None or hi is None:
                continue
            for a, b in ranges:
                if lo <= b and hi >= a:
                    raise ValidationError(f"Score range {lo}–{hi} overlaps another band.")
            ranges.append((lo, hi))


BandFormSet = inlineformset_factory(GradingScheme, GradeBand, form=BandForm, formset=BaseBandFormSet, extra=2, can_delete=True)
ClassFormSet = inlineformset_factory(GradingScheme, ClassificationBand, form=ClassForm, extra=1, can_delete=True)

SCHEME_CRUD = Crud("scheme", GradingScheme, SchemeForm, ("manage_grading",), "Grading systems", "Grading system",
                   section="Results", inlines=[("Grade bands", BandFormSet), ("Diploma classification", ClassFormSet)],
                   description="Score boundaries, letter grades, grade points, pass marks and diploma classes. Assign a system to each programme.",
                   list_display=[("Grading system", "name"), ("Pass mark", "pass_mark"), ("CGPA policy", "cgpa_policy"), ("Source", "source")])


# ---------------------------------------------------------------------------
# Lecturer & staff screens
# ---------------------------------------------------------------------------
@staff_required("upload_results")
def my_courses(request):
    semester = Semester.objects.filter(pk=request.GET.get("semester")).first() if request.GET.get("semester") else Semester.current()
    allocs = CourseAllocation.objects.filter(lecturer=request.user).select_related("course__programme", "semester__session")
    if semester:
        allocs = allocs.filter(semester=semester)
    sheets = {(s.course_id, s.semester_id): s for s in ResultSheet.objects.filter(course__in=[a.course_id for a in allocs])}
    rows = [{"a": a, "sheet": sheets.get((a.course_id, a.semester_id)), "students": registered_items(a.course, a.semester).count()} for a in allocs]
    return render(request, "results/my_courses.html", {"rows": rows, "semester": semester,
                                                       "semesters": Semester.objects.select_related("session")[:10]})


def _can_view_sheet(user, course, semester):
    if has_any(user, "manage_all_results", "approve_results", "publish_results", "generate_transcripts"):
        return True
    if has_perm(user, "review_results") and course.programme.department.hod_id == user.id:
        return True
    return has_perm(user, "upload_results") and services.is_allocated(user, course, semester)


@staff_required("upload_results", "review_results", "approve_results", "publish_results", "manage_all_results")
def open_sheet(request, course_id, semester_id):
    course = get_object_or_404(Course.objects.select_related("programme__department"), pk=course_id)
    semester = get_object_or_404(Semester, pk=semester_id)
    if not _can_view_sheet(request.user, course, semester):
        raise PermissionDenied("This course is not allocated to you.")
    sheet = services.get_or_create_sheet(course, semester, request.user)
    return redirect("results:sheet", sheet.pk)


@staff_required("upload_results", "review_results", "approve_results", "publish_results", "manage_all_results", "generate_transcripts")
def sheet_detail(request, pk):
    sheet = get_object_or_404(ResultSheet.objects.select_related("course__programme__department", "course__programme__grading_scheme",
                                                                 "semester__session"), pk=pk)
    user = request.user
    if not _can_view_sheet(user, sheet.course, sheet.semester):
        raise PermissionDenied
    if sheet.is_editable:
        services.sync_sheet_students(sheet)
    can_edit = services.can_enter_scores(user, sheet)
    if request.method == "POST":
        action = request.POST.get("action")
        note = request.POST.get("note", "").strip()
        try:
            if action == "save_scores":
                if not can_edit:
                    raise PermissionDenied
                entries = {}
                for score in sheet.scores.all():
                    ca_raw, ex_raw = request.POST.get(f"ca_{score.pk}"), request.POST.get(f"exam_{score.pk}")
                    if ca_raw is None and ex_raw is None:
                        continue
                    entries[score.student_id] = (services.parse_score(ca_raw, sheet.ca_max, f"{score.student.matric_number} CA"),
                                                 services.parse_score(ex_raw, sheet.exam_max, f"{score.student.matric_number} Exam"))
                n = services.save_scores(sheet, entries, user, reason=note)
                messages.success(request, f"{n} score(s) saved.")
            elif action == "submit":
                services.submit_sheet(sheet, user)
                messages.success(request, "Result submitted to the Head of Department.")
            elif action in ("hod_approve", "hod_return"):
                services.hod_review(sheet, action == "hod_approve", user, note)
                messages.success(request, "Review recorded.")
            elif action in ("approve", "return"):
                services.final_approval(sheet, action == "approve", user, note)
                messages.success(request, "Decision recorded.")
            elif action == "publish":
                services.publish(sheet, user)
                messages.success(request, "Result published. Students can now see it.")
            elif action == "unpublish":
                services.unpublish(sheet, user, note)
                messages.success(request, "Result unpublished.")
            elif action == "reopen":
                services.reopen(sheet, user, note)
                messages.success(request, "Result reopened for correction.")
            elif action == "recompute" and has_perm(user, "manage_all_results"):
                services.recompute_sheet(sheet)
                messages.success(request, "Grades recomputed from the current grading system.")
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        return redirect("results:sheet", pk)

    scores = list(sheet.scores.select_related("student", "updated_by"))
    complete = [s for s in scores if s.total is not None]
    dist = Counter(s.grade for s in complete)
    bands = list(sheet.scheme.bands.all())
    stats = {
        "count": len(scores), "complete": len(complete),
        "passed": sum(1 for s in complete if s.passed),
        "average": (sum(s.total for s in complete) / len(complete)).quantize(Decimal("0.1")) if complete else None,
        "highest": max((s.total for s in complete), default=None), "lowest": min((s.total for s in complete), default=None),
        "dist": [(b.letter, dist.get(b.letter, 0)) for b in bands] if not sheet.course.pass_fail_only else [("P", dist.get("P", 0)), ("F", dist.get("F", 0))],
    }
    if request.GET.get("export") == "xlsx":
        rows = [[s.student.matric_number, s.student.full_name, s.ca, s.exam, s.total, s.grade, s.points, s.remark] for s in scores]
        return export_response(f"result_{sheet.course.code.replace(' ', '')}.xlsx",
                               ["Matric Number", "Student Name", f"CA ({sheet.ca_max:g})", f"Exam ({sheet.exam_max:g})", "Total", "Grade", "Points", "Remark"], rows)
    if request.GET.get("export") == "pdf":
        return render_pdf("pdf/course_result.html", {"sheet": sheet, "scores": scores, "stats": stats}, f"result_{sheet.course.code}.pdf", request)
    is_hod = has_perm(user, "review_results") and services.is_hod_for(user, sheet)
    return render(request, "results/sheet.html", {
        "sheet": sheet, "scores": scores, "stats": stats, "can_edit": can_edit,
        "is_lecturer": services.is_allocated(user, sheet.course, sheet.semester), "is_hod": is_hod,
        "events": sheet.events.select_related("actor"),
    })


@staff_required("upload_results", "review_results", "approve_results", "publish_results", "manage_all_results", "generate_transcripts")
def staff_list(request):
    qs = services.sheets_for(request.user)
    semester = Semester.objects.filter(pk=request.GET.get("semester")).first() if request.GET.get("semester") else Semester.current()
    if semester:
        qs = qs.filter(semester=semester)
    for key, field in (("status", "status"), ("programme", "course__programme_id")):
        if request.GET.get(key):
            qs = qs.filter(**{field: request.GET[key]})
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(course__code__icontains=q) | qs.filter(course__title__icontains=q)
    page = Paginator(qs.order_by("course__programme__code", "course__code"), 40).get_page(request.GET.get("page"))
    missing = []
    if semester and has_any(request.user, "manage_all_results", "approve_results"):
        have = set(ResultSheet.objects.filter(semester=semester).values_list("course_id", flat=True))
        missing = (Course.objects.filter(term=semester.term, is_active=True, registrations__registration__semester=semester)
                   .exclude(pk__in=have).distinct().select_related("programme"))
    return render(request, "results/staff_list.html", {
        "page": page, "semester": semester, "semesters": Semester.objects.select_related("session")[:10],
        "programmes": Programme.objects.all(), "statuses": ResultSheet.STATUS_CHOICES, "missing": missing, "q": q})


@staff_required("generate_transcripts", "approve_results", "review_results", "manage_all_results")
def broadsheet(request):
    """Semester result sheet: all students of a programme/level with every course, GPA and CGPA."""
    programme = Programme.objects.filter(pk=request.GET.get("programme")).first()
    semester = Semester.objects.filter(pk=request.GET.get("semester")).first() or Semester.current()
    year = int(request.GET.get("year") or 1)
    include_unpublished = request.GET.get("all") == "1" and has_any(request.user, "approve_results", "manage_all_results")
    data = None
    if programme and semester:
        sheets = ResultSheet.objects.filter(semester=semester, course__programme=programme)
        if not include_unpublished:
            sheets = sheets.filter(status=ResultSheet.PUBLISHED)
        sheets = list(sheets.select_related("course").order_by("course__code"))
        students = Student.objects.filter(programme=programme, registrations__semester=semester,
                                          registrations__year_of_study=year).distinct().order_by("matric_number")
        rows = []
        for st in students:
            cells, units, points = [], 0, Decimal("0")
            for sh in sheets:
                sc = sh.scores.filter(student=st).first()
                cells.append(sc)
                if sc and sc.total is not None and not sh.course.pass_fail_only:
                    units += sc.credit_units
                    points += (sc.points or 0) * sc.credit_units
            gpa = (points / units).quantize(Decimal("0.01")) if units else None
            cgpa = services.cgpa_for(st)
            failed = [sh.course.code for sh, sc in zip(sheets, cells) if sc and sc.total is not None and not sc.passed]
            rows.append({"s": st, "cells": cells, "units": units, "gpa": gpa, "cgpa": cgpa, "failed": failed,
                         "remark": "Pass" if not failed else "Carry over: " + ", ".join(failed)})
        data = {"sheets": sheets, "rows": rows}
        if request.GET.get("export") == "xlsx":
            headers = ["Matric Number", "Name"] + [f"{sh.course.code} ({sh.course.credit_units})" for sh in sheets] + ["Units", "GPA", "CGPA", "Remark"]
            xrows = [[r["s"].matric_number, r["s"].full_name] + [f"{c.total:g} {c.grade}" if c and c.total is not None else "" for c in r["cells"]]
                     + [r["units"], r["gpa"], r["cgpa"], r["remark"]] for r in rows]
            return export_response(f"broadsheet_{programme.code}_Y{year}.xlsx", headers, xrows, "Broadsheet")
        if request.GET.get("export") == "pdf":
            return render_pdf("pdf/broadsheet.html", {"programme": programme, "semester": semester, "year": year, "data": data,
                                                       "level_label": programme.level_name(year)},
                              f"broadsheet_{programme.code}_Y{year}.pdf", request)
    return render(request, "results/broadsheet.html", {
        "programmes": Programme.objects.all(), "semesters": Semester.objects.select_related("session")[:10],
        "programme": programme, "semester": semester, "year": year, "data": data, "include_unpublished": include_unpublished})


@staff_required("generate_transcripts")
def transcript(request, pk):
    student = get_object_or_404(Student.objects.select_related("programme__department", "entry_session"), pk=pk)
    record = services.academic_record(student)
    from apps.core import audit
    audit.log(request.user, "transcript_generated", student, on_behalf_of=student.user)
    return render_pdf("pdf/transcript.html", {"s": student, "record": record, "official": True},
                      f"transcript_{student.matric_number.replace('/', '-')}.pdf", request)


# ---------------------------------------------------------------------------
# Student portal
# ---------------------------------------------------------------------------
@student_required
def portal_results(request):
    record = services.academic_record(request.student)
    if request.GET.get("print") == "1":
        return render_pdf("pdf/transcript.html", {"s": request.student, "record": record, "official": False},
                          "statement_of_results.pdf", request)
    return render(request, "results/portal_results.html", {"s": request.student, "record": record})
