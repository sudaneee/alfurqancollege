"""Student record business logic (shared by staff screens, bulk imports and admission conversion)."""
import secrets

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core import audit
from apps.core.models import SiteSettings

from .models import AcademicHistory, MatricSequence, Student, StudentStatus, StudentStatusHistory

User = get_user_model()

PERSONAL_FIELDS = [
    "first_name", "middle_name", "last_name", "gender", "date_of_birth", "phone", "email", "address",
    "state_of_origin", "lga", "nationality", "next_of_kin_name", "next_of_kin_relationship", "next_of_kin_phone",
    "next_of_kin_address", "guardian_name", "guardian_phone", "guardian_address",
]


def generate_matric_number(programme, session):
    fmt = SiteSettings.load().matric_number_format
    with transaction.atomic():
        seq, _ = MatricSequence.objects.select_for_update().get_or_create(programme=programme, session=session)
        while True:
            seq.last_serial += 1
            number = fmt.format(programme=programme.code, year=session.start_year, yy=str(session.start_year)[-2:],
                                serial=seq.last_serial)
            if not Student.objects.filter(matric_number__iexact=number).exists():
                break
        seq.save(update_fields=["last_serial"])
    return number


def temporary_password():
    return "Afc-" + secrets.token_urlsafe(6)


@transaction.atomic
def create_student(data, actor, *, programme, session, matric_number=None, status=None, user=None, application=None,
                   current_year=1, current_term=1, password=None, is_sample=False):
    """Create a student record and its login account. Returns (student, temp_password or None)."""
    if matric_number:
        matric_number = matric_number.strip().upper()
        if Student.objects.filter(matric_number__iexact=matric_number).exists():
            raise ValidationError(f"Matric number {matric_number} already exists.")
    else:
        matric_number = generate_matric_number(programme, session)
    if application is not None and Student.objects.filter(application=application).exists():
        raise ValidationError("This application has already been converted to a student record.")
    if user is not None and hasattr(user, "student"):
        raise ValidationError("This account already has a student record.")
    status = status or StudentStatus.get("admitted") or StudentStatus.objects.first()
    email = (data.get("email") or "").strip()
    temp = None
    if user is None:
        if email and User.objects.filter(email__iexact=email).exists():
            raise ValidationError(f"The e-mail {email} is already used by another account.")
        temp = password or temporary_password()
        user = User(username=matric_number, email=email, user_type=User.STUDENT, is_sample=is_sample,
                    must_change_password=password is None)
        user.set_password(temp)
    user.first_name = data.get("first_name", user.first_name)
    user.last_name = data.get("last_name", user.last_name)
    user.other_names = data.get("middle_name", "") or ""
    user.phone = data.get("phone", "") or user.phone
    user.user_type = User.STUDENT
    user.save()
    student = Student(user=user, matric_number=matric_number, programme=programme, entry_session=session,
                      current_year=current_year, current_term=current_term, status=status, application=application,
                      date_admitted=timezone.localdate(), created_by=actor, is_sample=is_sample)
    for f in PERSONAL_FIELDS + ["previous_education"]:
        if f in data and data[f] not in (None,):
            setattr(student, f, data[f])
    student.full_clean(exclude=["user", "application", "photo"])
    student.save()
    AcademicHistory.objects.create(student=student, session=session, event="admitted", to_year=current_year,
                                   recorded_by=actor)
    audit.log(actor, "student_created", student, on_behalf_of=user, changes={"matric_number": matric_number})
    return student, temp


@transaction.atomic
def update_student(student, data, actor, allowed_fields=None):
    before = audit.snapshot(student)
    fields = allowed_fields or (PERSONAL_FIELDS + ["previous_education"])
    for f in fields:
        if f in data:
            setattr(student, f, data[f])
    student.full_clean(exclude=["user", "application", "photo"])
    student.save()
    u = student.user
    u.first_name, u.last_name, u.other_names = student.first_name, student.last_name, student.middle_name
    if student.email and student.email.lower() != (u.email or "").lower():
        if User.objects.filter(email__iexact=student.email).exclude(pk=u.pk).exists():
            raise ValidationError("That e-mail address is used by another account.")
        u.email = student.email
    u.phone = student.phone
    u.save()
    changes = audit.diff(before, audit.snapshot(student))
    if changes:
        audit.log(actor, "student_updated", student, changes=changes, on_behalf_of=student.user)
    return changes


@transaction.atomic
def change_status(student, new_status, actor, reason=""):
    if student.status_id == new_status.id:
        return False
    StudentStatusHistory.objects.create(student=student, from_status=student.status, to_status=new_status,
                                        reason=reason, changed_by=actor)
    old = student.status
    student.status = new_status
    if new_status.code == "graduated" and not student.graduation_date:
        student.graduation_date = timezone.localdate()
    student.save(update_fields=["status", "graduation_date", "updated_at"])
    student.user.is_active = new_status.can_login
    student.user.save(update_fields=["is_active"])
    audit.log(actor, "student_status_changed", student, changes={"status": [str(old), str(new_status)]},
              note=reason, on_behalf_of=student.user)
    return True


@transaction.atomic
def promote(student, actor, session, note=""):
    """Move a student to the next year. Final-year students cannot be promoted."""
    if student.is_final_year:
        raise ValidationError(f"{student.matric_number} is in the final year of {student.programme.name}.")
    old = student.current_year
    student.current_year += 1
    student.current_term = 1
    student.save(update_fields=["current_year", "current_term", "updated_at"])
    AcademicHistory.objects.create(student=student, session=session, event="promoted", from_year=old,
                                   to_year=student.current_year, note=note, recorded_by=actor)
    audit.log(actor, "student_promoted", student, changes={"current_year": [old, student.current_year]},
              on_behalf_of=student.user)
