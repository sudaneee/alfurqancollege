from django.core.exceptions import ValidationError

from apps.academics.models import AcademicSession, Programme
from apps.accounts.models import User
from apps.core import parsing
from apps.core.bulk import BaseImporter, Column, RowError, register

from . import services
from .models import STATE_CHOICES, Student, StudentStatus

BIODATA_COLUMNS = [
    Column("first_name", "First Name", True, "Aisha"),
    Column("middle_name", "Middle Name", False, ""),
    Column("last_name", "Surname", True, "Bello"),
    Column("gender", "Gender", False, "Female", choices=["Male", "Female"]),
    Column("date_of_birth", "Date of Birth", False, "2004-05-17", help="YYYY-MM-DD"),
    Column("phone", "Phone", False, "08030000000"),
    Column("email", "Email", False, ""),
    Column("address", "Address", False, ""),
    Column("state_of_origin", "State of Origin", False, "Gombe"),
    Column("lga", "LGA", False, ""),
    Column("next_of_kin_name", "Next of Kin Name", False, ""),
    Column("next_of_kin_relationship", "Next of Kin Relationship", False, ""),
    Column("next_of_kin_phone", "Next of Kin Phone", False, ""),
    Column("guardian_name", "Guardian Name", False, ""),
    Column("guardian_phone", "Guardian Phone", False, ""),
]
STATES = {s.lower(): s for s, _ in STATE_CHOICES}


def clean_biodata(data, partial=False):
    out = {}
    for key in ("first_name", "middle_name", "last_name", "address", "lga", "next_of_kin_name",
                "next_of_kin_relationship", "guardian_name"):
        if not partial or data.get(key, "") != "":
            out[key] = str(data.get(key, "")).strip()
    for key in ("phone", "next_of_kin_phone", "guardian_phone"):
        if not partial or data.get(key, "") != "":
            out[key] = parsing.clean_phone(data.get(key))
    if not partial or data.get("gender", "") != "":
        out["gender"] = parsing.parse_gender(data.get("gender"))
    if not partial or data.get("date_of_birth", "") != "":
        out["date_of_birth"] = parsing.parse_date(data.get("date_of_birth"), "Date of birth")
    if not partial or data.get("email", "") != "":
        out["email"] = parsing.clean_email(data.get("email"))
    if not partial or data.get("state_of_origin", "") != "":
        st = str(data.get("state_of_origin", "")).strip()
        if st and st.lower() not in STATES:
            raise ValidationError(f"Unknown state '{st}'.")
        out["state_of_origin"] = STATES.get(st.lower(), "")
    return out


def _err(exc):
    return exc.messages if hasattr(exc, "messages") else [str(exc)]


@register
class StudentCreateImporter(BaseImporter):
    kind = "students_create"
    title = "Import new students"
    description = ("Create student records and login accounts in bulk. Leave Matric Number empty to generate one "
                   "automatically using the configured format. Existing matric numbers are rejected — use "
                   "'Bulk update students' to change existing records.")
    permissions = ("manage_students",)
    back_url_name = "students:list"
    columns = [
        Column("matric_number", "Matric Number", False, "", help="Optional. Generated automatically when empty."),
        Column("programme", "Programme Code", True, "PHT", help="e.g. PHT, NUD, HIM, CHE"),
        Column("session", "Session of Admission", True, "2025/2026"),
        Column("current_year", "Current Year", True, 1, help="Year of study (1, 2, 3...)"),
        Column("status", "Status Code", False, "active", help="Defaults to 'admitted'"),
    ] + BIODATA_COLUMNS

    def prepare(self, context):
        return {
            "programmes": {p.code.upper(): p for p in Programme.objects.all()},
            "sessions": {s.name: s for s in AcademicSession.objects.all()},
            "statuses": {s.code: s for s in StudentStatus.objects.all()},
            "seen_matric": set(), "seen_email": set(),
        }

    def _clean(self, data, state):
        prog = state["programmes"].get(str(data["programme"]).strip().upper())
        if not prog:
            raise RowError(f"Unknown programme code '{data['programme']}'.")
        session = state["sessions"].get(str(data["session"]).strip())
        if not session:
            raise RowError(f"Unknown session '{data['session']}'.")
        try:
            year = int(data["current_year"])
        except (TypeError, ValueError):
            raise RowError("Current Year must be a number.")
        if not 1 <= year <= prog.duration_years:
            raise RowError(f"{prog.name} runs for {prog.duration_years} year(s).")
        code = str(data.get("status") or "admitted").strip().lower()
        status = state["statuses"].get(code)
        if not status:
            raise RowError(f"Unknown status '{code}'.")
        bio = clean_biodata(data)
        return prog, session, year, status, bio

    def validate_row(self, data, context, state):
        try:
            prog, session, year, status, bio = self._clean(data, state)
        except ValidationError as exc:
            return _err(exc), "", {}
        errors = []
        matric = str(data.get("matric_number", "")).strip().upper()
        if matric:
            if matric in state["seen_matric"]:
                errors.append(f"Matric number {matric} appears more than once in this file.")
            elif Student.objects.filter(matric_number__iexact=matric).exists():
                errors.append(f"Matric number {matric} already exists.")
            state["seen_matric"].add(matric)
        email = bio.get("email")
        if email:
            if email in state["seen_email"]:
                errors.append(f"E-mail {email} appears more than once in this file.")
            elif User.objects.filter(email__iexact=email).exists():
                errors.append(f"E-mail {email} is already used by another account.")
            state["seen_email"].add(email)
        dup = Student.objects.filter(first_name__iexact=bio["first_name"], last_name__iexact=bio["last_name"],
                                     date_of_birth=bio.get("date_of_birth"), programme=prog)
        if bio.get("date_of_birth") and dup.exists():
            errors.append(f"Possible duplicate of existing student {dup.first().matric_number} (same name, birth date, programme).")
        return errors, "create", {}

    def apply_row(self, data, context, actor, state):
        prog, session, year, status, bio = self._clean(data, state)
        student, temp = services.create_student(bio, actor, programme=prog, session=session, current_year=year,
                                                status=status, matric_number=data.get("matric_number") or None)
        return f"Created {student.matric_number} (temporary password: {temp})"


@register
class StudentUpdateImporter(BaseImporter):
    kind = "students_update"
    title = "Bulk update students"
    description = ("Update existing student records by matric number. Only non-empty cells are applied; empty "
                   "cells leave the current value unchanged. The preview shows every value that will change.")
    permissions = ("manage_students",)
    back_url_name = "students:list"
    columns = [Column("matric_number", "Matric Number", True, "AFC/PHT/25/0001")] + [
        Column(c.key, c.label, False, "", c.help, c.choices) for c in BIODATA_COLUMNS
    ]

    def template_rows(self, context):
        rows = []
        for s in Student.objects.order_by("matric_number")[:2000] if context.get("prefill") else []:
            rows.append([s.matric_number] + [getattr(s, c.key) or "" for c in BIODATA_COLUMNS])
        return rows or [[c.example for c in self.columns]]

    def prepare(self, context):
        return {"seen": set()}

    def validate_row(self, data, context, state):
        matric = str(data["matric_number"]).strip()
        student = Student.objects.filter(matric_number__iexact=matric).first()
        if not student:
            return [f"No student with matric number {matric}."], "", {}
        if matric.upper() in state["seen"]:
            return [f"{matric} appears more than once in this file."], "", {}
        state["seen"].add(matric.upper())
        try:
            values = clean_biodata(data, partial=True)
        except ValidationError as exc:
            return _err(exc), "", {}
        if values.get("email") and User.objects.filter(email__iexact=values["email"]).exclude(pk=student.user_id).exists():
            return [f"E-mail {values['email']} is used by another account."], "", {}
        changes = {k: [str(getattr(student, k) or ""), str(v or "")] for k, v in values.items()
                   if str(getattr(student, k) or "") != str(v or "")}
        return [], "update" if changes else "skip", changes

    def apply_row(self, data, context, actor, state):
        student = Student.objects.get(matric_number__iexact=str(data["matric_number"]).strip())
        changes = services.update_student(student, clean_biodata(data, partial=True), actor)
        return f"Updated {len(changes)} field(s)"


@register
class StudentStatusImporter(BaseImporter):
    kind = "students_status"
    title = "Bulk status change"
    description = "Change the status of many students at once (e.g. suspended, withdrawn, graduated)."
    permissions = ("change_student_status",)
    back_url_name = "students:list"
    columns = [Column("matric_number", "Matric Number", True, "AFC/PHT/25/0001"),
               Column("status", "New Status Code", True, "active"),
               Column("reason", "Reason", False, "")]

    def notes(self, context):
        return super().notes(context) + ["Status codes: " + ", ".join(StudentStatus.objects.values_list("code", flat=True))]

    def validate_row(self, data, context, state):
        student = Student.objects.filter(matric_number__iexact=str(data["matric_number"]).strip()).select_related("status").first()
        if not student:
            return [f"No student with matric number {data['matric_number']}."], "", {}
        status = StudentStatus.objects.filter(code=str(data["status"]).strip().lower()).first()
        if not status:
            return [f"Unknown status '{data['status']}'."], "", {}
        if status.id == student.status_id:
            return [], "skip", {}
        return [], "update", {"status": [str(student.status), str(status)]}

    def apply_row(self, data, context, actor, state):
        student = Student.objects.get(matric_number__iexact=str(data["matric_number"]).strip())
        status = StudentStatus.objects.get(code=str(data["status"]).strip().lower())
        services.change_status(student, status, actor, data.get("reason", ""))
        return f"Status → {status}"
