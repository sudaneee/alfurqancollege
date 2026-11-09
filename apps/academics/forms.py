from django import forms
from django.contrib.auth import get_user_model

from apps.core.forms import StyledForm, StyledModelForm

from .models import (AcademicDocument, AcademicSession, CalendarEvent, Course, CourseAllocation, Department,
                     PracticalRequirement, Programme, Semester)

User = get_user_model()


class DepartmentForm(StyledModelForm):
    class Meta:
        model = Department
        fields = ["name", "code", "hod", "description", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["hod"].queryset = User.objects.filter(user_type="staff", is_active=True)


class ProgrammeForm(StyledModelForm):
    class Meta:
        model = Programme
        exclude = ["slug"]


class SessionForm(StyledModelForm):
    class Meta:
        model = AcademicSession
        fields = ["name", "start_date", "end_date", "is_current"]


class SemesterForm(StyledModelForm):
    class Meta:
        model = Semester
        fields = ["session", "term", "start_date", "end_date", "registration_opens", "registration_closes",
                  "add_drop_closes", "results_entry_open", "is_current"]


class CourseForm(StyledModelForm):
    class Meta:
        model = Course
        fields = ["programme", "code", "title", "credit_units", "year", "term", "course_type", "lecture_hours",
                  "tutorial_hours", "practical_hours", "contact_hours", "is_compulsory", "pass_fail_only",
                  "prerequisites", "description", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Course.objects.select_related("programme")
        if self.instance.pk:
            qs = qs.filter(programme=self.instance.programme).exclude(pk=self.instance.pk)
        self.fields["prerequisites"].queryset = qs
        self.fields["prerequisites"].help_text = "Courses that must be passed before this one (same programme)."

    def clean(self):
        data = super().clean()
        prog, year = data.get("programme"), data.get("year")
        if prog and year and year > prog.duration_years:
            self.add_error("year", f"{prog.name} runs for {prog.duration_years} year(s).")
        for p in data.get("prerequisites") or []:
            if prog and p.programme_id != prog.id:
                self.add_error("prerequisites", f"{p.code} belongs to another programme.")
        return data


class PracticalForm(StyledModelForm):
    class Meta:
        model = PracticalRequirement
        fields = ["programme", "kind", "title", "year", "term", "timing", "duration", "assessment", "course", "is_mandatory", "order"]


class CalendarEventForm(StyledModelForm):
    class Meta:
        model = CalendarEvent
        fields = ["session", "title", "category", "start_date", "end_date", "description", "is_public"]


class AcademicDocumentForm(StyledModelForm):
    class Meta:
        model = AcademicDocument
        fields = ["title", "file", "programme", "description", "is_public"]


class AllocationForm(StyledForm):
    semester = forms.ModelChoiceField(queryset=Semester.objects.select_related("session"))
    programme = forms.ModelChoiceField(queryset=Programme.objects.all(), required=False,
                                       help_text="Optional: narrows the course list")
    course = forms.ModelChoiceField(queryset=Course.objects.filter(is_active=True).select_related("programme"))
    lecturer = forms.ModelChoiceField(queryset=User.objects.filter(user_type="staff", is_active=True).order_by("first_name"))
    is_coordinator = forms.BooleanField(required=False, initial=True, label="Course coordinator (uploads results)")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["course"].label_from_instance = lambda c: f"{c.code} — {c.title} ({c.programme.code}, {c.slot_label})"
        self.fields["semester"].initial = Semester.current()

    def clean(self):
        data = super().clean()
        c, s = data.get("course"), data.get("semester")
        if c and s and c.term != s.term:
            self.add_error("course", f"{c.code} is a {c.get_term_display()} course.")
        if c and s and data.get("lecturer") and CourseAllocation.objects.filter(course=c, semester=s, lecturer=data["lecturer"]).exists():
            self.add_error("lecturer", "This lecturer is already allocated to this course for the semester.")
        return data
