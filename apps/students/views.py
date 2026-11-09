from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.academics.models import AcademicSession, Programme, Semester
from apps.core import audit
from apps.core.crud import Crud
from apps.core.excel import export_response
from apps.core.models import AuditLog
from apps.core.permissions import has_perm, staff_required, student_required

from . import forms, services
from .models import AcademicHistory, DocumentType, Student, StudentDocument, StudentStatus

STATUS_CRUD = Crud("status", StudentStatus, forms.StatusForm, ("change_student_status", "manage_settings"),
                   "Student statuses", "Status", section="System settings",
                   description="Statuses control whether a student can sign in, register courses and is counted as enrolled.",
                   list_display=[("Status", "name"), ("Code", "code"), ("Can register", "can_register_courses"),
                                 ("Can sign in", "can_login"), ("Counts as enrolled", "counts_as_enrolled")])


def _filtered(request):
    qs = Student.objects.select_related("programme", "status", "entry_session")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(matric_number__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)
                       | Q(middle_name__icontains=q) | Q(phone__icontains=q) | Q(email__icontains=q))
    for key, field in (("programme", "programme_id"), ("status", "status__code"), ("session", "entry_session_id"),
                       ("year", "current_year")):
        val = request.GET.get(key)
        if val:
            qs = qs.filter(**{field: val})
    if request.GET.get("sample") == "1":
        qs = qs.filter(is_sample=True)
    elif request.GET.get("sample") == "0":
        qs = qs.filter(is_sample=False)
    return qs


@staff_required("view_students", "manage_students")
def student_list(request):
    qs = _filtered(request)
    if request.GET.get("export") == "xlsx":
        headers = ["Matric Number", "Surname", "First Name", "Middle Name", "Gender", "Date of Birth", "Programme", "Level",
                   "Semester", "Status", "Session of Admission", "Phone", "Email", "State", "LGA", "Next of Kin",
                   "Next of Kin Phone", "Sample record"]
        rows = [[s.matric_number, s.last_name, s.first_name, s.middle_name, s.get_gender_display(), s.date_of_birth,
                 s.programme.name, s.level_label, s.get_current_term_display(), s.status.name, s.entry_session.name,
                 s.phone, s.email, s.state_of_origin, s.lga, s.next_of_kin_name, s.next_of_kin_phone,
                 "Yes" if s.is_sample else ""] for s in qs]
        audit.log(request.user, "students_exported", None, module="students", object_repr=f"{len(rows)} students")
        return export_response("students.xlsx", headers, rows, "Students")
    page = Paginator(qs.order_by("matric_number"), 30).get_page(request.GET.get("page"))
    return render(request, "students/staff/list.html", {
        "page": page, "programmes": Programme.objects.all(), "statuses": StudentStatus.objects.all(),
        "sessions": AcademicSession.objects.all(), "q": request.GET.get("q", ""),
    })


@staff_required("manage_students")
def student_create(request):
    form = forms.StudentCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            student, temp = services.create_student(
                {f: d.get(f) for f in services.PERSONAL_FIELDS + ["previous_education"]}, request.user,
                programme=d["programme"], session=d["entry_session"], matric_number=d.get("matric_number") or None,
                status=d["status"], current_year=d["current_year"], current_term=d["current_term"])
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"Student {student.matric_number} created. Portal sign-in: {student.matric_number} / "
                                      f"temporary password {temp} (must be changed at first sign-in).")
            return redirect("students:detail", student.pk)
    return render(request, "students/staff/form.html", {"form": form, "title": "New student"})


@staff_required("view_students", "manage_students")
def student_detail(request, pk):
    student = get_object_or_404(Student.objects.select_related("programme__department", "status", "entry_session", "user", "application"), pk=pk)
    from apps.bursary.services import student_financial_summary
    from apps.results.services import academic_record
    tab = request.GET.get("tab", "profile")
    ctx = {"s": student, "tab": tab, "status_form": forms.StatusChangeForm(initial={"status": student.status}),
           "doc_form": forms.DocumentUploadForm()}
    if tab == "academic":
        ctx["registrations"] = student.registrations.select_related("semester__session").prefetch_related("items__course")
        ctx["record"] = academic_record(student)
    elif tab == "finance" and has_perm(request.user, "view_finance"):
        ctx["fin"] = student_financial_summary(student)
    elif tab == "history":
        ctx["status_history"] = student.status_history.select_related("from_status", "to_status", "changed_by")
        ctx["academic_history"] = student.academic_history.select_related("session", "recorded_by")
        ctx["audit"] = AuditLog.objects.filter(Q(object_type="students.Student", object_id=str(student.pk)) | Q(on_behalf_of=student.user)).select_related("actor")[:40]
        if student.application_id:
            ctx["app_events"] = student.application.events.select_related("actor")
    else:
        from apps.results.services import cgpa_for
        ctx["cgpa"] = cgpa_for(student)
    ctx["documents"] = student.documents.select_related("document_type", "uploaded_by")
    return render(request, "students/staff/detail.html", ctx)


@staff_required("manage_students")
def student_edit(request, pk):
    student = get_object_or_404(Student, pk=pk)
    old_prog, old_year = student.programme_id, student.current_year
    form = forms.StudentEditForm(request.POST or None, request.FILES or None, instance=student)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                before = audit.snapshot(Student.objects.get(pk=pk))
                s = form.save()
                services.update_student(s, {}, request.user)  # syncs login account
                changes = audit.diff(before, audit.snapshot(s))
                if changes:
                    audit.log(request.user, "student_updated", s, changes=changes, on_behalf_of=s.user)
                if (old_prog, old_year) != (s.programme_id, s.current_year):
                    AcademicHistory.objects.create(student=s, session=AcademicSession.current() or s.entry_session, event="changed",
                                                   from_year=old_year, to_year=s.current_year, recorded_by=request.user,
                                                   note="Programme/level changed by staff")
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Student record updated.")
            return redirect("students:detail", pk)
    return render(request, "students/staff/form.html", {"form": form, "title": f"Edit {student.display_name}", "object": student})


@staff_required("change_student_status")
@require_POST
def student_status(request, pk):
    student = get_object_or_404(Student, pk=pk)
    form = forms.StatusChangeForm(request.POST)
    if form.is_valid():
        if services.change_status(student, form.cleaned_data["status"], request.user, form.cleaned_data["reason"]):
            messages.success(request, f"Status changed to {form.cleaned_data['status']}.")
        else:
            messages.info(request, "The student already has that status.")
    else:
        messages.error(request, "Choose a status and give a reason.")
    return redirect("students:detail", pk)


def _save_document(request, student, form):
    doc = form.save(commit=False)
    doc.student = student
    doc.uploaded_by = request.user
    doc.save()
    audit.log(request.user, "student_document_uploaded", doc, on_behalf_of=student.user, module="students")
    return doc


@staff_required("manage_students")
@require_POST
def student_document_upload(request, pk):
    student = get_object_or_404(Student, pk=pk)
    form = forms.DocumentUploadForm(request.POST, request.FILES)
    if form.is_valid():
        _save_document(request, student, form)
        messages.success(request, "Document uploaded.")
    else:
        messages.error(request, "; ".join(e for errs in form.errors.values() for e in errs))
    return redirect(f"/staff/students/{pk}/?tab=documents")


@staff_required("manage_students")
@require_POST
def student_document_verify(request, pk, doc_id):
    doc = get_object_or_404(StudentDocument, pk=doc_id, student_id=pk)
    doc.is_verified, doc.verified_by = True, request.user
    doc.save(update_fields=["is_verified", "verified_by"])
    audit.log(request.user, "student_document_verified", doc, on_behalf_of=doc.student.user)
    messages.success(request, "Document marked as verified.")
    return redirect(f"/staff/students/{pk}/?tab=documents")


@staff_required("promote_students")
def promote(request):
    form = forms.PromotionFilterForm(request.GET or None)
    students = []
    if form.is_valid():
        d = form.cleaned_data
        students = (Student.objects.filter(programme=d["programme"], current_year=d["year"], status__counts_as_enrolled=True)
                    .select_related("status").order_by("matric_number"))
        if request.method == "POST":
            ids = request.POST.getlist("students")
            done, errors = 0, []
            for s in students.filter(pk__in=ids):
                try:
                    services.promote(s, request.user, d["session"])
                    done += 1
                except ValidationError as exc:
                    errors.append("; ".join(exc.messages))
            if done:
                messages.success(request, f"{done} student(s) promoted to {d['programme'].level_name(d['year'] + 1)}.")
            for e in errors:
                messages.error(request, e)
            return redirect(request.get_full_path())
        from apps.results.services import academic_record
        enriched = []
        for s in students:
            rec = academic_record(s)
            enriched.append({"s": s, "cgpa": rec["cgpa"], "outstanding": rec["outstanding"]})
        students = enriched
    return render(request, "students/staff/promote.html", {"form": form, "rows": students})


# ---------------------------------------------------------------------------
# Student portal
# ---------------------------------------------------------------------------
@student_required
def portal_dashboard(request):
    from apps.bursary.services import student_financial_summary
    from apps.registration.models import CourseRegistration
    from apps.results.services import cgpa_for
    from apps.website.models import Post

    s = request.student
    semester = Semester.current()
    reg = CourseRegistration.objects.filter(student=s, semester=semester).first() if semester else None
    cgpa = cgpa_for(s)
    uploaded = set(s.documents.values_list("document_type_id", flat=True))
    return render(request, "students/portal/dashboard.html", {
        "s": s, "semester": semester, "reg": reg, "cgpa": cgpa,
        "classification": s.programme.grading_scheme.classify(cgpa) if cgpa is not None else "",
        "fin": student_financial_summary(s),
        "posts": Post.visible(("public", "students"))[:5],
        "notes": request.user.notifications.all()[:5],
        "missing_docs": DocumentType.objects.filter(required_for_students=True).exclude(pk__in=uploaded),
    })


@student_required
def portal_profile(request):
    s = request.student
    form = forms.StudentSelfEditForm(request.POST or None, instance=s)
    if request.method == "POST" and form.is_valid():
        try:
            services.update_student(s, {f: form.cleaned_data[f] for f in Student.SELF_EDITABLE}, request.user,
                                    allowed_fields=Student.SELF_EDITABLE)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Your profile has been updated.")
            return redirect("students:portal_profile")
    return render(request, "students/portal/profile.html", {"s": s, "form": form})


@student_required
def portal_documents(request):
    s = request.student
    form = forms.DocumentUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        _save_document(request, s, form)
        messages.success(request, "Document uploaded. The Registry will verify it.")
        return redirect("students:portal_documents")
    from apps.academics.models import AcademicDocument
    downloads = AcademicDocument.objects.filter(Q(programme=s.programme) | Q(programme__isnull=True))
    return render(request, "students/portal/documents.html", {"s": s, "form": form, "documents": s.documents.select_related("document_type"),
                                                              "downloads": downloads})


@student_required
def portal_announcements(request):
    from apps.website.models import Post
    page = Paginator(Post.visible(("public", "students")), 12).get_page(request.GET.get("page"))
    return render(request, "students/portal/announcements.html", {"page": page})
