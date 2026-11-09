"""Admission workflow shared by the applicant portal, staff screens and bulk imports."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core import audit
from apps.core.models import SiteSettings
from apps.core.sequences import next_value
from apps.notifications.services import notify

from .models import Application, ApplicationEvent


def via_staff(application, actor):
    return bool(actor and actor.pk != application.user_id)


def record_event(application, action, actor, note=""):
    ApplicationEvent.objects.create(application=application, action=action, note=note, actor=actor,
                                    via_staff=via_staff(application, actor))


def assign_number(application):
    if application.application_number:
        return application.application_number
    year = application.period.session.start_year
    fmt = SiteSettings.load().application_number_format
    while True:
        number = fmt.format(year=year, serial=next_value(f"application-{year}"))
        if not Application.objects.filter(application_number=number).exists():
            break
    application.application_number = number
    application.save(update_fields=["application_number"])
    return number


@transaction.atomic
def submit(application, actor, force=False):
    """Submit an application. Staff with authority may `force` past missing items (recorded)."""
    application = Application.objects.select_for_update().get(pk=application.pk)
    if application.status not in (Application.DRAFT,):
        raise ValidationError("This application has already been submitted.")
    if not application.period.is_open() and not (force and via_staff(application, actor)):
        raise ValidationError("The application period is closed.")
    missing = application.missing_items()
    if missing and not force:
        raise ValidationError("Please complete: " + "; ".join(missing))
    assign_number(application)
    application.status = Application.SUBMITTED
    application.submitted_at = timezone.now()
    application.save()
    record_event(application, "Submitted", actor, "Missing items overridden: " + "; ".join(missing) if missing else "")
    audit.log(actor, "application_submitted", application, on_behalf_of=application.user)
    notify(application.user, "application_submitted", {"number": application.application_number,
                                                       "programme": application.first_choice.name})
    return application


@transaction.atomic
def grant_fee_exemption(application, actor, reason):
    application.fee_exempt = True
    application.fee_exemption_reason = reason
    application.fee_exempted_by = actor
    application.save(update_fields=["fee_exempt", "fee_exemption_reason", "fee_exempted_by"])
    for inv in application.invoices.filter(purpose="application").exclude(status="cancelled"):
        if not inv.payments.filter(status="successful").exists():
            inv.status = "cancelled"
            inv.save(update_fields=["status"])
    record_event(application, "Application fee exemption granted", actor, reason)
    audit.log(actor, "application_fee_exemption", application, note=reason, on_behalf_of=application.user)


DECISIONS = {"admit": Application.ADMITTED, "reject": Application.NOT_ADMITTED, "review": Application.UNDER_REVIEW}


@transaction.atomic
def decide(application, decision, actor, programme=None, note=""):
    if decision not in DECISIONS:
        raise ValidationError("Unknown decision.")
    application = Application.objects.select_for_update().get(pk=application.pk)
    if application.status in (Application.DRAFT, Application.WITHDRAWN):
        raise ValidationError("Only submitted applications can be processed.")
    if application.is_converted:
        raise ValidationError("This applicant has already accepted admission and is now a student.")
    old = application.status
    application.status = DECISIONS[decision]
    if decision == "admit":
        application.admitted_programme = programme or application.admitted_programme or application.first_choice
        application.offer_status = Application.OFFER_PENDING
    elif decision == "reject":
        application.offer_status = ""
    application.decision_note = note
    application.decided_by = actor
    application.decided_at = timezone.now()
    application.save()
    record_event(application, f"Decision: {application.get_status_display()}", actor, note)
    audit.log(actor, "admission_decision", application, changes={"status": [old, application.status]}, note=note,
              on_behalf_of=application.user)
    if decision == "admit":
        notify(application.user, "admission_offered", {"programme": application.admitted_programme.name,
                                                       "number": application.application_number},
               link="/apply/")
    elif decision == "reject":
        notify(application.user, "admission_not_offered", {"number": application.application_number})
    return application


@transaction.atomic
def respond_to_offer(application, accept, actor, matric_number=None):
    """Accept or decline an admission offer. Acceptance converts the applicant into a student."""
    application = Application.objects.select_for_update().get(pk=application.pk)
    if application.status != Application.ADMITTED:
        raise ValidationError("There is no admission offer to respond to.")
    if application.offer_status == Application.OFFER_ACCEPTED or application.is_converted:
        raise ValidationError("This offer has already been accepted.")
    if not accept:
        application.offer_status = Application.OFFER_DECLINED
        application.offer_responded_at = timezone.now()
        application.save()
        record_event(application, "Admission offer declined", actor)
        audit.log(actor, "admission_declined", application, on_behalf_of=application.user)
        return None
    student = convert_to_student(application, actor, matric_number=matric_number)
    application.offer_status = Application.OFFER_ACCEPTED
    application.offer_responded_at = timezone.now()
    application.save()
    record_event(application, "Admission offer accepted", actor, f"Matric number {student.matric_number}")
    return student


def convert_to_student(application, actor, matric_number=None):
    """Create the student record from the application. Never creates duplicates."""
    from apps.bursary.models import FeeItem
    from apps.bursary.services import generate_student_invoice
    from apps.students.services import PERSONAL_FIELDS, create_student

    if application.is_converted:
        return application.student
    data = {f: getattr(application, f) for f in PERSONAL_FIELDS}
    olevels = "; ".join(f"{o.exam_type} {o.exam_year} – {o.subject}: {o.grade}" for o in application.olevels.all())
    data["previous_education"] = "\n".join(p for p in [application.previous_institution, olevels,
                                                         application.other_qualifications] if p)
    student, _ = create_student(data, actor, programme=application.admitted_programme or application.first_choice,
                                session=application.period.session, matric_number=matric_number,
                                user=application.user, application=application,
                                is_sample=application.is_sample)
    session = application.period.session
    generate_student_invoice(student, session, actor, stage=FeeItem.ACCEPTANCE, year=1)
    generate_student_invoice(student, session, actor, stage=FeeItem.STUDENT, year=1)
    notify(student.user, "admission_accepted", {"matric": student.matric_number, "programme": student.programme.name},
           link="/student/")
    return student
