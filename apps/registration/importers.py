from django.core.exceptions import ValidationError

from apps.academics.models import Course, Semester
from apps.core import parsing
from apps.core.bulk import BaseImporter, Column, RowError, register
from apps.students.models import Student

from . import services
from .models import CourseRegistration, RegisteredCourse


def _semester(context):
    sid = context.get("semester")
    sem = Semester.objects.filter(pk=sid).select_related("session").first() if sid else Semester.current()
    if not sem:
        raise RowError("No current semester is configured.")
    return sem


@register
class CourseRegistrationImporter(BaseImporter):
    kind = "course_registration"
    title = "Bulk course registration"
    description = ("Register, add or drop courses for many students at once. List course codes separated by commas, "
                   "or write ALL to register every course for the student's level this semester. The same rules as "
                   "online registration apply (deadlines, prerequisites, credit limits, duplicates).")
    permissions = ("manage_registrations",)
    back_url_name = "registration:staff_list"
    context_keys = ("semester",)
    columns = [
        Column("matric_number", "Matric Number", True, "AFC/PHT/25/0001"),
        Column("action", "Action", True, "add", choices=["add", "drop"]),
        Column("courses", "Course Codes", True, "ALL", help="Comma-separated codes, or ALL"),
        Column("submit", "Submit Registration", False, "Yes", choices=["Yes", "No"]),
    ]

    def context_label(self, context):
        try:
            return f"({_semester(context)})"
        except RowError:
            return ""

    def prepare(self, context):
        return {"seen": set()}

    def _resolve(self, data, context):
        sem = _semester(context)
        student = Student.objects.filter(matric_number__iexact=str(data["matric_number"]).strip()).select_related("programme", "status").first()
        if not student:
            raise RowError(f"No student with matric number {data['matric_number']}.")
        action = str(data["action"]).strip().lower()
        if action not in ("add", "drop"):
            raise RowError("Action must be add or drop.")
        text = str(data["courses"]).strip()
        if text.upper() == "ALL":
            if action != "add":
                raise RowError("ALL can only be used with the add action.")
            avail, _ = services.available_courses(student, sem)
            reg = CourseRegistration.objects.filter(student=student, semester=sem).first()
            done = set(reg.items.values_list("course_id", flat=True)) if reg else set()
            courses = [c for c in avail.filter(year=student.current_year) if c.id not in done]
        else:
            courses, codes = [], [c.strip().upper() for c in text.split(",") if c.strip()]
            for code in codes:
                matches = list(Course.objects.filter(programme=student.programme, code__iexact=code, term=sem.term))
                if not matches:
                    raise RowError(f"{code} is not a {sem.get_term_display()} course in {student.programme.name}.")
                matches.sort(key=lambda c: (c.year != student.current_year, c.year))
                courses.append(matches[0])
        return sem, student, action, courses

    def validate_row(self, data, context, state):
        try:
            sem, student, action, courses = self._resolve(data, context)
        except ValidationError as exc:
            return exc.messages, "", {}
        key = student.matric_number.upper()
        if key in state["seen"]:
            return [f"{student.matric_number} appears more than once; combine the courses into one row."], "", {}
        state["seen"].add(key)
        if not courses:
            return [], "skip", {}
        reg = CourseRegistration.objects.filter(student=student, semester=sem).first()
        errors = []
        if action == "add":
            if not student.status.can_register_courses and not services.can_override(self.actor):
                errors.append(f"Status '{student.status}' cannot register courses.")
            temp_reg = reg or CourseRegistration(student=student, semester=sem, year_of_study=student.current_year)
            for c in courses:
                try:
                    if reg:
                        services.validate_course(student, reg, c, self.actor)
                    else:
                        if c.programme_id != student.programme_id:
                            raise ValidationError(f"{c.code} is not in the student's programme.")
                except ValidationError as exc:
                    errors.extend(exc.messages)
            limit = student.programme.max_credit_units
            current = temp_reg.total_units if reg else 0
            total = current + sum(c.credit_units for c in courses)
            if limit and total > limit and not services.can_override(self.actor):
                errors.append(f"Total credit units ({total}) exceed the maximum of {limit}.")
        else:
            registered = set(reg.items.values_list("course_id", flat=True)) if reg else set()
            for c in courses:
                if c.id not in registered:
                    errors.append(f"{c.code} is not registered.")
        return errors, "update", {"courses": ["", f"{action}: " + ", ".join(c.code for c in courses)]}

    def apply_row(self, data, context, actor, state):
        sem, student, action, courses = self._resolve(data, context)
        if action == "add":
            reg = services.add_courses(student, sem, courses, actor)
        else:
            reg = CourseRegistration.objects.get(student=student, semester=sem)
            for c in courses:
                services.drop_course(reg, c, actor, "Bulk drop")
        reg.refresh_from_db()
        if parsing.parse_bool(data.get("submit")) and reg.status in (CourseRegistration.DRAFT, CourseRegistration.REJECTED):
            services.submit_registration(reg, actor)
            reg.refresh_from_db()
        return f"{action.title()}ed {len(courses)} course(s); {reg.total_units} units; {reg.get_status_display()}"
