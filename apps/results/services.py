"""Result processing: score entry, grading, approval workflow and GPA/CGPA."""
from collections import OrderedDict
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.academics.models import CourseAllocation
from apps.core import audit
from apps.core.permissions import has_perm
from apps.notifications.services import notify
from apps.registration.services import registered_items

from .models import ResultSheet, ResultSheetEvent, Score

TWO = Decimal("0.01")


# ---------------------------------------------------------------------------
# Access scoping
# ---------------------------------------------------------------------------
def sheets_for(user):
    qs = ResultSheet.objects.select_related("course__programme__department", "semester__session")
    if has_perm(user, "manage_all_results") or has_perm(user, "approve_results") or has_perm(user, "publish_results"):
        return qs
    cond = Q(pk__in=[])
    if has_perm(user, "review_results"):
        cond |= Q(course__programme__department__hod=user)
    if has_perm(user, "upload_results"):
        alloc = CourseAllocation.objects.filter(lecturer=user).values_list("course_id", "semester_id")
        for course_id, semester_id in alloc:
            cond |= Q(course_id=course_id, semester_id=semester_id)
    return qs.filter(cond)


def is_allocated(user, course, semester):
    return CourseAllocation.objects.filter(lecturer=user, course=course, semester=semester).exists()


def can_enter_scores(user, sheet):
    if has_perm(user, "manage_all_results"):
        return True
    return sheet.is_editable and has_perm(user, "upload_results") and is_allocated(user, sheet.course, sheet.semester)


def is_hod_for(user, sheet):
    return sheet.course.programme.department.hod_id == user.id


# ---------------------------------------------------------------------------
# Sheets and scores
# ---------------------------------------------------------------------------
@transaction.atomic
def get_or_create_sheet(course, semester, actor):
    programme = course.programme
    sheet, created = ResultSheet.objects.get_or_create(
        course=course, semester=semester,
        defaults={"ca_max": programme.ca_max_score, "exam_max": programme.exam_max_score, "created_by": actor},
    )
    if created:
        ResultSheetEvent.objects.create(sheet=sheet, action="created", to_status=sheet.status, actor=actor)
    sync_sheet_students(sheet)
    return sheet


def sync_sheet_students(sheet):
    """Ensure every registered student has a score row (no duplicates)."""
    existing = set(sheet.scores.values_list("student_id", flat=True))
    new = []
    for item in registered_items(sheet.course, sheet.semester):
        sid = item.registration.student_id
        if sid not in existing:
            new.append(Score(sheet=sheet, student_id=sid, registered_course=item, credit_units=sheet.course.credit_units))
            existing.add(sid)
    if new:
        Score.objects.bulk_create(new)
    return len(new)


def parse_score(value, maximum, label):
    if value is None or str(value).strip() == "":
        return None
    try:
        num = Decimal(str(value).strip()).quantize(TWO, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise ValidationError(f"{label} '{value}' is not a number.")
    if num < 0:
        raise ValidationError(f"{label} cannot be negative.")
    if num > maximum:
        raise ValidationError(f"{label} {num} exceeds the maximum of {maximum}.")
    return num


@transaction.atomic
def save_scores(sheet, entries, actor, reason=""):
    """entries: {student_id: (ca, exam)} already parsed. Returns number of changed rows.

    Locked sheets (submitted onward) can only be changed by users with
    `manage_all_results`, and a reason is mandatory. Every change is audited.
    """
    sheet = ResultSheet.objects.select_for_update().get(pk=sheet.pk)
    if not can_enter_scores(actor, sheet):
        raise PermissionDenied("You cannot modify scores on this result sheet.")
    if not sheet.is_editable and not reason.strip():
        raise ValidationError("A reason is required to modify a result that has left draft.")
    scores = {s.student_id: s for s in sheet.scores.select_related("student", "sheet__course__programme__grading_scheme")}
    changed = 0
    for student_id, (ca, exam) in entries.items():
        score = scores.get(student_id)
        if score is None:
            raise ValidationError("A student on the upload is not registered for this course.")
        old = (score.ca, score.exam, score.total, score.grade)
        score.ca, score.exam = ca, exam
        score.compute()
        if old != (score.ca, score.exam, score.total, score.grade):
            score.updated_by = actor
            score.save()
            changed += 1
            audit.log(actor, "score_changed", score, module="results", note=reason,
                      changes={"ca": [str(old[0]), str(score.ca)], "exam": [str(old[1]), str(score.exam)],
                               "total": [str(old[2]), str(score.total)], "grade": [old[3], score.grade],
                               "sheet_status": sheet.status})
    if changed and not sheet.is_editable:
        ResultSheetEvent.objects.create(sheet=sheet, action="scores_corrected", from_status=sheet.status,
                                        to_status=sheet.status, note=f"{changed} score(s): {reason}", actor=actor)
    return changed


def recompute_sheet(sheet):
    for s in sheet.scores.select_related("sheet__course__programme__grading_scheme"):
        s.compute()
        s.save(update_fields=["total", "grade", "points", "remark"])


# ---------------------------------------------------------------------------
# Workflow: draft → submitted → hod_approved → approved → published
# ---------------------------------------------------------------------------
def _transition(sheet, to_status, actor, action, note="", stamp=None):
    old = sheet.status
    sheet.status = to_status
    if stamp:
        setattr(sheet, f"{stamp}_by", actor)
        setattr(sheet, f"{stamp}_at", timezone.now())
    sheet.save()
    ResultSheetEvent.objects.create(sheet=sheet, action=action, from_status=old, to_status=to_status, note=note, actor=actor)
    audit.log(actor, f"result_{action}", sheet, module="results", changes={"status": [old, to_status]}, note=note)


@transaction.atomic
def submit_sheet(sheet, actor):
    sheet = ResultSheet.objects.select_for_update().get(pk=sheet.pk)
    if not sheet.is_editable:
        raise ValidationError("Only draft or returned results can be submitted.")
    if not (has_perm(actor, "manage_all_results") or is_allocated(actor, sheet.course, sheet.semester)):
        raise PermissionDenied("Only the course lecturer can submit this result.")
    if not sheet.scores.exists():
        raise ValidationError("There are no students on this result sheet.")
    incomplete = sheet.scores.filter(Q(ca__isnull=True) | Q(exam__isnull=True)).count()
    if incomplete:
        raise ValidationError(f"{incomplete} student(s) have missing CA or exam scores.")
    _transition(sheet, ResultSheet.SUBMITTED, actor, "submitted", stamp="submitted")
    hod = sheet.course.programme.department.hod
    if hod:
        notify(hod, "result_submitted", {"course": sheet.course.code, "semester": str(sheet.semester)}, link="/staff/results/")


@transaction.atomic
def hod_review(sheet, approve, actor, note=""):
    sheet = ResultSheet.objects.select_for_update().get(pk=sheet.pk)
    if sheet.status != ResultSheet.SUBMITTED:
        raise ValidationError("This result is not awaiting HOD review.")
    if not (has_perm(actor, "manage_all_results") or (has_perm(actor, "review_results") and is_hod_for(actor, sheet))):
        raise PermissionDenied("Only the Head of Department can review this result.")
    if not approve and not note.strip():
        raise ValidationError("Give a reason when returning a result for correction.")
    if approve:
        _transition(sheet, ResultSheet.HOD_APPROVED, actor, "hod_approved", note, stamp="hod_reviewed")
    else:
        _transition(sheet, ResultSheet.RETURNED, actor, "returned", note, stamp="hod_reviewed")
        if sheet.submitted_by:
            notify(sheet.submitted_by, "result_returned", {"course": sheet.course.code, "note": note}, link="/staff/results/")


@transaction.atomic
def final_approval(sheet, approve, actor, note=""):
    sheet = ResultSheet.objects.select_for_update().get(pk=sheet.pk)
    if sheet.status != ResultSheet.HOD_APPROVED:
        raise ValidationError("This result has not been reviewed by the HOD yet.")
    if not (has_perm(actor, "approve_results") or has_perm(actor, "manage_all_results")):
        raise PermissionDenied("You cannot approve results.")
    if not approve and not note.strip():
        raise ValidationError("Give a reason when returning a result.")
    if approve:
        _transition(sheet, ResultSheet.APPROVED, actor, "approved", note, stamp="approved")
    else:
        _transition(sheet, ResultSheet.RETURNED, actor, "returned", note)


@transaction.atomic
def publish(sheet, actor):
    sheet = ResultSheet.objects.select_for_update().get(pk=sheet.pk)
    if sheet.status != ResultSheet.APPROVED:
        raise ValidationError("Only approved results can be published.")
    if not has_perm(actor, "publish_results"):
        raise PermissionDenied("You cannot publish results.")
    _transition(sheet, ResultSheet.PUBLISHED, actor, "published", stamp="published")
    for score in sheet.scores.select_related("student__user"):
        notify(score.student.user, "result_published", {"course": sheet.course.code, "semester": str(sheet.semester)},
               link="/student/results/")


@transaction.atomic
def unpublish(sheet, actor, note):
    sheet = ResultSheet.objects.select_for_update().get(pk=sheet.pk)
    if sheet.status != ResultSheet.PUBLISHED:
        raise ValidationError("This result is not published.")
    if not has_perm(actor, "publish_results") or not note.strip():
        raise ValidationError("A reason is required to unpublish a result.")
    _transition(sheet, ResultSheet.APPROVED, actor, "unpublished", note)


@transaction.atomic
def reopen(sheet, actor, note):
    sheet = ResultSheet.objects.select_for_update().get(pk=sheet.pk)
    if not has_perm(actor, "manage_all_results"):
        raise PermissionDenied("Only authorised officers can reopen results.")
    if sheet.is_editable:
        raise ValidationError("This result is already open for editing.")
    if not note.strip():
        raise ValidationError("A reason is required to reopen a result.")
    _transition(sheet, ResultSheet.DRAFT, actor, "reopened", note)


# ---------------------------------------------------------------------------
# GPA / CGPA
# ---------------------------------------------------------------------------
def _gpa(scores):
    units = sum(s.credit_units for s in scores)
    points = sum((s.points or 0) * s.credit_units for s in scores)
    if not units:
        return None, 0, Decimal("0")
    return (Decimal(points) / units).quantize(TWO, rounding=ROUND_HALF_UP), units, Decimal(points)


def published_scores(student):
    return (Score.objects.filter(student=student, sheet__status=ResultSheet.PUBLISHED, total__isnull=False)
            .select_related("sheet__course", "sheet__semester__session")
            .order_by("sheet__semester__session__start_date", "sheet__semester__term", "sheet__course__code"))


def counted(scores, scheme):
    """Apply the CGPA policy and exclude pass/fail courses."""
    scores = [s for s in scores if not s.sheet.course.pass_fail_only]
    if scheme.cgpa_policy == scheme.LATEST_ATTEMPT:
        latest = OrderedDict()
        for s in scores:
            latest[s.sheet.course_id] = s
        return list(latest.values())
    return scores


def academic_record(student):
    """Semester-by-semester published results with GPA and running CGPA."""
    scheme = student.programme.grading_scheme
    all_scores = list(published_scores(student))
    semesters = OrderedDict()
    for s in all_scores:
        semesters.setdefault(s.sheet.semester, []).append(s)
    record, cumulative = [], []
    for semester, scores in semesters.items():
        cumulative.extend(scores)
        gpa, units, points = _gpa([s for s in scores if not s.sheet.course.pass_fail_only])
        cgpa, cum_units, cum_points = _gpa(counted(cumulative, scheme))
        record.append({
            "semester": semester, "scores": scores, "gpa": gpa, "units": units, "points": points,
            "cgpa": cgpa, "cum_units": cum_units, "cum_points": cum_points,
            "failed": [s for s in scores if not s.passed],
        })
    cgpa = record[-1]["cgpa"] if record else None
    earned = sum(s.credit_units for s in all_scores if s.passed)
    return {
        "semesters": record, "cgpa": cgpa, "classification": scheme.classify(cgpa) if cgpa is not None else "",
        "credits_earned": earned, "scheme": scheme,
        "outstanding": sorted({s.sheet.course.code for s in all_scores if not s.passed}
                              - {s.sheet.course.code for s in all_scores if s.passed}),
    }


def cgpa_for(student):
    scheme = student.programme.grading_scheme
    cgpa, _, _ = _gpa(counted(list(published_scores(student)), scheme))
    return cgpa
