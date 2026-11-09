from django import forms

from apps.academics.models import AcademicSession, Programme
from apps.core.forms import StyledForm, StyledModelForm

from .models import DocumentType, Student, StudentDocument, StudentStatus
from .services import PERSONAL_FIELDS

BIO_SECTIONS = [
    ("Personal details", "bi-person", ["first_name", "middle_name", "last_name", "gender", "date_of_birth",
                                       "state_of_origin", "lga", "nationality"]),
    ("Contact", "bi-telephone", ["phone", "email", "address"]),
    ("Next of kin", "bi-people", ["next_of_kin_name", "next_of_kin_relationship", "next_of_kin_phone", "next_of_kin_address"]),
    ("Parent / guardian", "bi-house-heart", ["guardian_name", "guardian_phone", "guardian_address"]),
]


class SectionedMixin:
    sections_spec = BIO_SECTIONS

    def sections(self):
        used = set()
        for title, icon, names in self.sections_spec:
            fields = [self[n] for n in names if n in self.fields]
            used.update(names)
            if fields:
                yield title, icon, fields
        rest = [self[n] for n in self.fields if n not in used]
        if rest:
            yield "Other", "bi-three-dots", rest


class StudentCreateForm(SectionedMixin, StyledModelForm):
    matric_number = forms.CharField(required=False, help_text="Leave empty to generate automatically.")
    sections_spec = [("Academic placement", "bi-mortarboard", ["programme", "entry_session", "current_year", "current_term", "status", "matric_number"])] + BIO_SECTIONS + [
        ("Background", "bi-journal-text", ["previous_education"])]

    class Meta:
        model = Student
        fields = ["programme", "entry_session", "current_year", "current_term", "status"] + PERSONAL_FIELDS + ["previous_education"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["entry_session"].initial = AcademicSession.current()
        self.fields["status"].initial = StudentStatus.get("admitted")

    def clean_matric_number(self):
        m = self.cleaned_data.get("matric_number", "").strip().upper()
        if m and Student.objects.filter(matric_number__iexact=m).exists():
            raise forms.ValidationError("This matric number already exists.")
        return m

    def clean(self):
        d = super().clean()
        p, y = d.get("programme"), d.get("current_year")
        if p and y and y > p.duration_years:
            self.add_error("current_year", f"{p.name} runs for {p.duration_years} year(s).")
        return d


class StudentEditForm(SectionedMixin, StyledModelForm):
    sections_spec = BIO_SECTIONS + [("Academic placement", "bi-mortarboard", ["programme", "current_year", "current_term"]),
                                    ("Background", "bi-journal-text", ["previous_education", "photo"])]

    class Meta:
        model = Student
        fields = PERSONAL_FIELDS + ["previous_education", "photo", "programme", "current_year", "current_term"]

    def clean(self):
        d = super().clean()
        p, y = d.get("programme"), d.get("current_year")
        if p and y and y > p.duration_years:
            self.add_error("current_year", f"{p.name} runs for {p.duration_years} year(s).")
        return d


class StudentSelfEditForm(SectionedMixin, StyledModelForm):
    class Meta:
        model = Student
        fields = Student.SELF_EDITABLE


class StatusChangeForm(StyledForm):
    status = forms.ModelChoiceField(queryset=StudentStatus.objects.all())
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=True)


class DocumentUploadForm(StyledModelForm):
    class Meta:
        model = StudentDocument
        fields = ["document_type", "file"]


class PromotionFilterForm(StyledForm):
    programme = forms.ModelChoiceField(queryset=Programme.objects.all())
    year = forms.IntegerField(min_value=1, max_value=6, label="Current year")
    session = forms.ModelChoiceField(queryset=AcademicSession.objects.all(), label="Promote into session",
                                     help_text="The session the promotion is recorded against")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["session"].initial = AcademicSession.current()


class StatusForm(StyledModelForm):
    class Meta:
        model = StudentStatus
        fields = ["name", "code", "description", "can_register_courses", "can_login", "counts_as_enrolled", "order"]


class DocumentTypeForm(StyledModelForm):
    class Meta:
        model = DocumentType
        fields = ["name", "description", "required_for_application", "required_for_students", "order"]
