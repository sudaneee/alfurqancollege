"""Course registration rules.

One code path for student self-service, staff-assisted registration and bulk
Excel registration. `actor` is whoever performs the action; when it differs
from the student, the action is recorded as performed on the student's behalf.
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.academics.models import Course
from apps.core import audit
from apps.core.models import SiteSettings
from apps.core.permissions import has_perm
from apps.notifications.services import notify

from .models import CourseRegistration, RegisteredCourse, RegistrationEvent


def is_staff_action(student, actor):
    return bool(actor and actor.pk != student.user_id)


def can_override(actor):
    return has_perm(actor, "override_registration_rules")


def passed_course_ids(student):
    """Courses the student has passed in published results."""
    from apps.results.models import ResultSheet, Score

    ids = set()
    for s in Score.objects.filter(student=student, sheet__status=ResultSheet.PUBLISHED).select_related("sheet__course__programme__grading_scheme"):
        if s.passed:
            ids.add(s.sheet.course_id)
    return ids


def failed_course_ids(student):
    from apps.results.models import ResultSheet, Score

    failed = set()
    for s in Score.objects.filter(student=student, sheet__status=ResultSheet.PUBLISHED).select_related("sheet__course__programme__grading_scheme"):
        if s.total is not None and not s.passed:
            failed.add(s.sheet.course_id)
    return failed - passed_course_ids(student)


def available_courses(student, semester):
    """Courses offered to this student this semester: their level's courses + carry-overs in the same term."""
    regular = Course.objects.filter(programme=student.programme, year=student.current_year, term=semester.term, is_active=True)
    carry_ids = failed_course_ids(student)
    carry = Course.objects.filter(pk__in=carry_ids, term=semester.term, is_active=True)
    passed = passed_course_ids(student)
    return (regular | carry).exclude(pk__in=passed).distinct().order_by("year", "code"), carry_ids


def get_or_create_registration(student, semester, actor):
    reg, created = CourseRegistration.objects.get_or_create(
        student=student, semester=semester,
        defaults={"year_of_study": student.current_year, "created_by": actor},
    )
    if created:
        RegistrationEvent.objects.create(registration=reg, action="created", actor=actor,
                                         via_staff=is_staff_action(student, actor))
    return reg


def _check_window(reg, actor, adding=True):
    semester = reg.semester
    if can_override(actor):
        return
    if reg.status == CourseRegistration.APPROVED:
        if not semester.add_drop_is_open():
            raise ValidationError("The add/drop period for this semester has closed.")
        return
    if not semester.registration_is_open():
        raise ValidationError("Course registration for this semester is closed.")


def _check_editable(reg, actor):
    if reg.status == CourseRegistration.SUBMITTED and not is_staff_action(reg.student, actor):
        raise ValidationError("Your registration has been submitted and is awaiting approval. "
                              "Contact your department to make changes.")
    if reg.status == CourseRegistration.APPROVED and not (has_perm(actor, "manage_registrations") or reg.semester.add_drop_is_open()):
        raise ValidationError("This registration is approved and can no longer be changed.")


def validate_course(student, reg, course, actor):
    if course.programme_id != student.programme_id:
        raise ValidationError(f"{course.code} is not part of {student.programme.name}.")
    if not course.is_active:
        raise ValidationError(f"{course.code} is not currently offered.")
    if course.term != reg.semester.term:
        raise ValidationError(f"{course.code} is a {course.get_term_display()} course.")
    if course.year > student.current_year and not can_override(actor):
        raise ValidationError(f"{course.code} is a {course.level_label} course; the student is in {student.level_label}.")
    if RegisteredCourse.objects.filter(registration=reg, course=course).exists():
        raise ValidationError(f"{course.code} is already registered this semester.")
    passed = passed_course_ids(student)
    if course.id in passed:
        raise ValidationError(f"{course.code} has already been passed.")
    missing = [p.code for p in course.prerequisites.all() if p.id not in passed]
    if missing and not can_override(actor):
        raise ValidationError(f"{course.code} requires {', '.join(missing)} to be passed first.")


def _check_credit_ceiling(reg, adding_units, actor):
    limit = reg.student.programme.max_credit_units
    total = reg.total_units + adding_units
    if limit and total > limit and not can_override(actor):
        raise ValidationError(f"Total credit units ({total}) would exceed the maximum of {limit} per semester.")


@transaction.atomic
def add_courses(student, semester, courses, actor):
    if not student.status.can_register_courses and not can_override(actor):
        raise ValidationError(f"Students with status '{student.status}' cannot register courses.")
    reg = get_or_create_registration(student, semester, actor)
    reg = CourseRegistration.objects.select_for_update().get(pk=reg.pk)
    _check_editable(reg, actor)
    _check_window(reg, actor)
    courses = list(courses)
    for c in courses:
        validate_course(student, reg, c, actor)
    _check_credit_ceiling(reg, sum(c.credit_units for c in courses), actor)
    carry = failed_course_ids(student)
    staff = is_staff_action(student, actor)
    for c in courses:
        RegisteredCourse.objects.create(registration=reg, course=c, added_by=actor,
                                        is_carryover=c.id in carry or c.year < student.current_year)
        RegistrationEvent.objects.create(registration=reg, action="added", course=c, actor=actor, via_staff=staff)
    if reg.status == CourseRegistration.REJECTED:
        reg.status = CourseRegistration.DRAFT
        reg.save(update_fields=["status"])
    audit.log(actor, "courses_added", reg, changes={"courses": [c.code for c in courses]}, on_behalf_of=student.user)
    return reg


@transaction.atomic
def drop_course(reg, course, actor, reason=""):
    reg = CourseRegistration.objects.select_for_update().get(pk=reg.pk)
    _check_editable(reg, actor)
    _check_window(reg, actor, adding=False)
    item = RegisteredCourse.objects.filter(registration=reg, course=course).first()
    if item is None:
        raise ValidationError(f"{course.code} is not registered.")
    if hasattr(item, "score") and item.score and item.score.total is not None:
        raise ValidationError(f"{course.code} already has a result and cannot be dropped.")
    item.delete()
    RegistrationEvent.objects.create(registration=reg, action="dropped", course=course, actor=actor, note=reason,
                                     via_staff=is_staff_action(reg.student, actor))
    audit.log(actor, "course_dropped", reg, changes={"course": course.code}, note=reason, on_behalf_of=reg.student.user)


@transaction.atomic
def submit_registration(reg, actor):
    reg = CourseRegistration.objects.select_for_update().get(pk=reg.pk)
    if reg.status not in (CourseRegistration.DRAFT, CourseRegistration.REJECTED):
        raise ValidationError("This registration has already been submitted.")
    if not reg.items.exists():
        raise ValidationError("Select at least one course before submitting.")
    minimum = reg.student.programme.min_credit_units
    if minimum and reg.total_units < minimum and not can_override(actor):
        raise ValidationError(f"You must register at least {minimum} credit units (currently {reg.total_units}).")
    reg.submitted_at = timezone.now()
    staff = is_staff_action(reg.student, actor)
    auto_approve = not SiteSettings.load().registration_requires_approval or (staff and has_perm(actor, "approve_registrations"))
    reg.status = CourseRegistration.APPROVED if auto_approve else CourseRegistration.SUBMITTED
    if auto_approve:
        reg.reviewed_by, reg.reviewed_at = actor, timezone.now()
    reg.save()
    RegistrationEvent.objects.create(registration=reg, action="submitted", actor=actor, via_staff=staff)
    if auto_approve:
        RegistrationEvent.objects.create(registration=reg, action="approved", actor=actor, via_staff=staff)
    _activate_student(reg.student, actor)
    audit.log(actor, "registration_submitted", reg, on_behalf_of=reg.student.user)
    return reg


def _activate_student(student, actor):
    from apps.students.models import StudentStatus
    from apps.students.services import change_status

    if student.status.code == "admitted":
        active = StudentStatus.get("active")
        if active:
            change_status(student, active, actor, "Activated on first course registration")


@transaction.atomic
def review_registration(reg, approve, actor, note=""):
    reg = CourseRegistration.objects.select_for_update().get(pk=reg.pk)
    if reg.status != CourseRegistration.SUBMITTED:
        raise ValidationError("Only submitted registrations can be reviewed.")
    reg.status = CourseRegistration.APPROVED if approve else CourseRegistration.REJECTED
    reg.reviewed_by, reg.reviewed_at, reg.review_note = actor, timezone.now(), note
    reg.save()
    RegistrationEvent.objects.create(registration=reg, action="approved" if approve else "returned", note=note, actor=actor,
                                     via_staff=True)
    audit.log(actor, "registration_approved" if approve else "registration_returned", reg, note=note,
              on_behalf_of=reg.student.user)
    notify(reg.student.user, "registration_reviewed",
           {"semester": str(reg.semester), "status": reg.get_status_display(), "note": note}, link="/student/courses/")
    return reg


COUNTED_STATUSES = (CourseRegistration.SUBMITTED, CourseRegistration.APPROVED)


def registered_items(course, semester):
    """Registered-course rows (submitted or approved) for a course in a semester."""
    return (RegisteredCourse.objects
            .filter(course=course, registration__semester=semester, registration__status__in=COUNTED_STATUSES)
            .select_related("registration__student")
            .order_by("registration__student__matric_number"))
