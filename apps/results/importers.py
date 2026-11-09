from django.core.exceptions import PermissionDenied, ValidationError

from apps.core.bulk import BaseImporter, Column, RowError, register

from . import services
from .models import ResultSheet


def _sheet(context):
    sheet = ResultSheet.objects.filter(pk=context.get("sheet")).select_related(
        "course__programme__grading_scheme", "semester__session").first()
    if not sheet:
        raise RowError("Result sheet not found.")
    return sheet


@register
class ScoreSheetImporter(BaseImporter):
    kind = "scores"
    title = "Upload score sheet"
    description = ("Download the score sheet for this course, enter CA and Examination scores, then upload it. "
                   "Totals and grades are calculated automatically — the Total column in the file is ignored.")
    permissions = ("upload_results", "manage_all_results")
    back_url_name = "results:staff_list"
    context_keys = ("sheet",)
    columns = [
        Column("matric_number", "Matric Number", True),
        Column("student_name", "Student Name", False),
        Column("ca", "CA", False),
        Column("exam", "Exam", False),
        Column("total", "Total", False),
    ]

    def check_access(self, user, context):
        super().check_access(user, context)
        sheet = _sheet(context)
        if not services.can_enter_scores(user, sheet):
            raise PermissionDenied("This result sheet is not open for you to edit.")

    def context_label(self, context):
        try:
            return f"({_sheet(context)})"
        except RowError:
            return ""

    def headers(self):
        return ["Matric Number", "Student Name", "CA", "Exam", "Total"]

    def template_rows(self, context):
        sheet = _sheet(context)
        services.sync_sheet_students(sheet)
        rows = []
        for i, s in enumerate(sheet.scores.select_related("student"), start=2):
            rows.append([s.student.matric_number, s.student.full_name,
                         float(s.ca) if s.ca is not None else None,
                         float(s.exam) if s.exam is not None else None,
                         f"=IF(AND(ISNUMBER(C{i}),ISNUMBER(D{i})),C{i}+D{i},\"\")"])
        return rows

    def template_filename(self, context):
        sheet = _sheet(context)
        return f"scoresheet_{sheet.course.code.replace(' ', '')}_{sheet.semester.session.name.replace('/', '-')}_S{sheet.semester.term}.xlsx"

    def notes(self, context):
        sheet = _sheet(context)
        return [
            f"Course: {sheet.course.code} — {sheet.course.title} ({sheet.course.credit_units} units)",
            f"Session/semester: {sheet.semester}",
            f"Maximum CA score: {sheet.ca_max}. Maximum Exam score: {sheet.exam_max}.",
            "Do not add or remove students; registration is managed in the portal.",
            "Leave a cell empty if the score is not yet available (the result cannot be submitted until complete).",
            "The Total column is calculated for your convenience; the system recalculates it on upload.",
        ]

    def prepare(self, context):
        sheet = _sheet(context)
        return {"sheet": sheet, "scores": {s.student.matric_number.upper(): s for s in sheet.scores.select_related("student")},
                "seen": set()}

    def _parse(self, data, state):
        sheet = state["sheet"]
        ca = services.parse_score(data.get("ca"), sheet.ca_max, "CA")
        exam = services.parse_score(data.get("exam"), sheet.exam_max, "Exam")
        return ca, exam

    def validate_row(self, data, context, state):
        matric = str(data["matric_number"]).strip().upper()
        score = state["scores"].get(matric)
        if score is None:
            return [f"{matric} is not registered for this course in this semester."], "", {}
        if matric in state["seen"]:
            return [f"{matric} appears more than once."], "", {}
        state["seen"].add(matric)
        name = str(data.get("student_name") or "").strip().lower()
        if name and score.student.last_name.lower() not in name:
            return [f"Name '{data['student_name']}' does not match {score.student.full_name} — check the matric number."], "", {}
        try:
            ca, exam = self._parse(data, state)
        except ValidationError as exc:
            return exc.messages, "", {}
        errors = []
        if ca is None or exam is None:
            errors_note = "Missing " + " and ".join(x for x, v in (("CA", ca), ("Exam", exam)) if v is None)
        else:
            errors_note = ""
        if (ca, exam) == (score.ca, score.exam):
            return errors, "skip", {}
        total = (ca or 0) + (exam or 0) if ca is not None and exam is not None else None
        changes = {"ca": [str(score.ca or ""), str(ca or "")], "exam": [str(score.exam or ""), str(exam or "")],
                   "total": [str(score.total or ""), str(total or "")]}
        if errors_note:
            changes["note"] = ["", errors_note]
        return errors, "update", changes

    def apply_row(self, data, context, actor, state):
        sheet = state["sheet"]
        score = state["scores"][str(data["matric_number"]).strip().upper()]
        ca, exam = self._parse(data, state)
        services.save_scores(sheet, {score.student_id: (ca, exam)}, actor, reason=context.get("reason", ""))
        score.refresh_from_db()
        return f"Total {score.total if score.total is not None else '—'} {score.grade}"
