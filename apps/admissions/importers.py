from django.core.exceptions import ValidationError

from apps.academics.models import Programme
from apps.accounts.models import User
from apps.core import parsing
from apps.core.bulk import BaseImporter, Column, RowError, register
from apps.students.importers import BIODATA_COLUMNS, clean_biodata
from apps.students.services import temporary_password

from . import services
from .models import Application, ApplicationPeriod


def _period(context):
    pid = context.get("period")
    period = ApplicationPeriod.objects.filter(pk=pid).first() if pid else ApplicationPeriod.current()
    if period is None:
        period = ApplicationPeriod.objects.filter(is_active=True).first()
    if period is None:
        raise RowError("No application period is configured.")
    return period


@register
class ApplicantCreateImporter(BaseImporter):
    kind = "applicants_create"
    title = "Register applicants in bulk"
    description = ("Create applicant accounts and applications on behalf of applicants (e.g. forms filled on paper). "
                   "Set 'Submit' to Yes to submit the application immediately; set 'Fee Exempt' to Yes to grant a free form.")
    permissions = ("process_admissions",)
    back_url_name = "admissions:staff_list"
    context_keys = ("period",)
    columns = [
        Column("programme", "Programme Code", True, "NUD"),
        Column("second_choice", "Second Choice Code", False, ""),
    ] + BIODATA_COLUMNS + [
        Column("fee_exempt", "Fee Exempt", False, "No", choices=["Yes", "No"]),
        Column("exemption_reason", "Exemption Reason", False, ""),
        Column("submit", "Submit", False, "Yes", choices=["Yes", "No"]),
    ]

    def context_label(self, context):
        try:
            return f"({_period(context).name})"
        except RowError:
            return ""

    def prepare(self, context):
        return {"programmes": {p.code.upper(): p for p in Programme.objects.all()}, "emails": set(), "names": set()}

    def _clean(self, data, context, state):
        period = _period(context)
        allowed = set(period.programmes.values_list("id", flat=True))
        prog = state["programmes"].get(str(data["programme"]).upper())
        if not prog:
            raise RowError(f"Unknown programme code '{data['programme']}'.")
        if prog.id not in allowed:
            raise RowError(f"{prog.name} is not open in {period.name}.")
        second = None
        if data.get("second_choice"):
            second = state["programmes"].get(str(data["second_choice"]).upper())
            if not second:
                raise RowError(f"Unknown second-choice code '{data['second_choice']}'.")
        bio = clean_biodata(data)
        return period, prog, second, bio

    def validate_row(self, data, context, state):
        try:
            period, prog, second, bio = self._clean(data, context, state)
        except ValidationError as exc:
            return exc.messages, "", {}
        errors = []
        email = bio.get("email")
        if email:
            if email in state["emails"]:
                errors.append(f"E-mail {email} appears more than once in this file.")
            elif User.objects.filter(email__iexact=email).exists():
                errors.append(f"E-mail {email} already has an account — update that application instead.")
            state["emails"].add(email)
        key = (bio["first_name"].lower(), bio["last_name"].lower(), str(bio.get("date_of_birth")), bio.get("phone"))
        if key in state["names"]:
            errors.append("This applicant appears more than once in the file.")
        state["names"].add(key)
        if bio.get("phone") and Application.objects.filter(period=period, phone=bio["phone"],
                                                           last_name__iexact=bio["last_name"]).exists():
            errors.append("An application with the same surname and phone already exists in this period.")
        if parsing.parse_bool(data.get("fee_exempt")) and not data.get("exemption_reason"):
            errors.append("Exemption Reason is required when Fee Exempt is Yes.")
        return errors, "create", {}

    def apply_row(self, data, context, actor, state):
        period, prog, second, bio = self._clean(data, context, state)
        username = bio.get("email") or f"app-{temporary_password().lower()}"
        user = User(username=username, email=bio.get("email", ""), first_name=bio["first_name"], last_name=bio["last_name"],
                    other_names=bio.get("middle_name", ""), phone=bio.get("phone", ""), user_type=User.APPLICANT,
                    must_change_password=True)
        temp = temporary_password()
        user.set_password(temp)
        user.save()
        app = Application.objects.create(user=user, period=period, first_choice=prog, second_choice=second,
                                         created_by=actor, **bio)
        services.record_event(app, "Created by staff", actor)
        services.assign_number(app)
        if parsing.parse_bool(data.get("fee_exempt")):
            services.grant_fee_exemption(app, actor, data.get("exemption_reason", ""))
        if parsing.parse_bool(data.get("submit"), default=True):
            services.submit(app, actor, force=True)
        return f"{app.application_number} created (login: {username} / {temp})"


@register
class AdmissionDecisionImporter(BaseImporter):
    kind = "admission_decisions"
    title = "Bulk admission decisions"
    description = ("Admit, decline or mark applications under review in bulk using application numbers. "
                   "Optionally admit into a different programme with 'Admit Into'.")
    permissions = ("process_admissions",)
    back_url_name = "admissions:staff_list"
    columns = [
        Column("application_number", "Application Number", True, "AFC/APP/2026/00001"),
        Column("decision", "Decision", True, "admit", choices=["admit", "reject", "review"]),
        Column("admit_into", "Admit Into (Programme Code)", False, ""),
        Column("note", "Note", False, ""),
    ]

    def template_rows(self, context):
        qs = Application.objects.filter(status__in=[Application.SUBMITTED, Application.UNDER_REVIEW]).select_related("first_choice")
        rows = [[a.application_number, "", a.first_choice.code, ""] for a in qs[:3000]]
        return rows or [[c.example for c in self.columns]]

    def prepare(self, context):
        return {"seen": set(), "programmes": {p.code.upper(): p for p in Programme.objects.all()}}

    def validate_row(self, data, context, state):
        number = str(data["application_number"]).strip()
        app = Application.objects.filter(application_number__iexact=number).first()
        if not app:
            return [f"No application {number}."], "", {}
        if number.upper() in state["seen"]:
            return [f"{number} appears more than once."], "", {}
        state["seen"].add(number.upper())
        decision = str(data["decision"]).strip().lower()
        if decision not in services.DECISIONS:
            return ["Decision must be admit, reject or review."], "", {}
        if app.status in (Application.DRAFT, Application.WITHDRAWN):
            return [f"{number} has not been submitted."], "", {}
        if app.is_converted:
            return [f"{number} has already been converted to a student."], "", {}
        if data.get("admit_into") and str(data["admit_into"]).upper() not in state["programmes"]:
            return [f"Unknown programme code '{data['admit_into']}'."], "", {}
        new_status = services.DECISIONS[decision]
        if new_status == app.status:
            return [], "skip", {}
        return [], "update", {"status": [app.get_status_display(), dict(Application.STATUS_CHOICES)[new_status]]}

    def apply_row(self, data, context, actor, state):
        app = Application.objects.get(application_number__iexact=str(data["application_number"]).strip())
        prog = state["programmes"].get(str(data.get("admit_into") or "").upper())
        services.decide(app, str(data["decision"]).strip().lower(), actor, programme=prog, note=data.get("note", ""))
        return "Decision recorded"


@register
class OfferResponseImporter(BaseImporter):
    kind = "offer_responses"
    title = "Accept admission on behalf of applicants"
    description = ("Record acceptance (or decline) of admission offers for admitted applicants. Acceptance converts "
                   "the applicant into a student, generates the matric number and the first invoices.")
    permissions = ("process_admissions",)
    back_url_name = "admissions:staff_list"
    columns = [
        Column("application_number", "Application Number", True, "AFC/APP/2026/00001"),
        Column("response", "Response", True, "accept", choices=["accept", "decline"]),
        Column("matric_number", "Matric Number (optional)", False, ""),
    ]

    def prepare(self, context):
        return {"seen": set()}

    def validate_row(self, data, context, state):
        number = str(data["application_number"]).strip()
        app = Application.objects.filter(application_number__iexact=number).first()
        if not app:
            return [f"No application {number}."], "", {}
        if number.upper() in state["seen"]:
            return [f"{number} appears more than once."], "", {}
        state["seen"].add(number.upper())
        if app.status != Application.ADMITTED:
            return [f"{number} has not been offered admission."], "", {}
        if app.offer_status == Application.OFFER_ACCEPTED or app.is_converted:
            return [], "skip", {}
        resp = str(data["response"]).strip().lower()
        if resp not in ("accept", "decline"):
            return ["Response must be accept or decline."], "", {}
        from apps.students.models import Student
        m = str(data.get("matric_number") or "").strip()
        if m and Student.objects.filter(matric_number__iexact=m).exists():
            return [f"Matric number {m} already exists."], "", {}
        return [], "update", {"offer": ["Awaiting response", resp.title()]}

    def apply_row(self, data, context, actor, state):
        app = Application.objects.get(application_number__iexact=str(data["application_number"]).strip())
        accept = str(data["response"]).strip().lower() == "accept"
        student = services.respond_to_offer(app, accept, actor, matric_number=(data.get("matric_number") or None))
        return f"Student {student.matric_number}" if student else "Declined"
