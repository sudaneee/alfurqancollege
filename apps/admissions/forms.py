from django import forms
from django.forms import inlineformset_factory

from apps.academics.models import Programme
from apps.core.forms import StyledForm, StyledModelForm
from apps.students.forms import BIO_SECTIONS, SectionedMixin

from .models import Application, ApplicationDocument, ApplicationPeriod, OLevelResult

APPLICATION_SECTIONS = [
    ("Programme choice", "bi-mortarboard", ["first_choice", "second_choice"]),
] + BIO_SECTIONS + [
    ("Education", "bi-journal-text", ["previous_institution", "jamb_reg_number", "jamb_score", "other_qualifications"]),
]


class ApplicationForm(SectionedMixin, StyledModelForm):
    sections_spec = APPLICATION_SECTIONS

    class Meta:
        model = Application
        fields = ["first_choice", "second_choice", "first_name", "middle_name", "last_name", "gender", "date_of_birth",
                  "state_of_origin", "lga", "nationality", "phone", "email", "address", "next_of_kin_name",
                  "next_of_kin_relationship", "next_of_kin_phone", "next_of_kin_address", "guardian_name",
                  "guardian_phone", "guardian_address", "previous_institution", "jamb_reg_number", "jamb_score",
                  "other_qualifications"]
        labels = {"previous_institution": "Secondary school attended"}

    def __init__(self, *args, period=None, **kwargs):
        super().__init__(*args, **kwargs)
        period = period or (self.instance.period if self.instance.pk else None)
        qs = period.programmes.filter(accepting_applications=True) if period else Programme.objects.none()
        self.fields["first_choice"].queryset = qs
        self.fields["second_choice"].queryset = qs
        for f in ("gender", "date_of_birth", "phone", "address", "state_of_origin"):
            self.fields[f].required = True

    def clean(self):
        d = super().clean()
        if d.get("first_choice") and d.get("first_choice") == d.get("second_choice"):
            self.add_error("second_choice", "Choose a different programme or leave empty.")
        return d


class StaffApplicationForm(ApplicationForm):
    """Used by admission officers registering an applicant who cannot apply online."""

    period = forms.ModelChoiceField(queryset=ApplicationPeriod.objects.all(), help_text="Application period")
    sections_spec = [("Application period", "bi-calendar-range", ["period"])] + APPLICATION_SECTIONS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["period"].initial = ApplicationPeriod.current() or ApplicationPeriod.objects.first()
        self.fields["first_choice"].queryset = Programme.objects.filter(accepting_applications=True)
        self.fields["second_choice"].queryset = Programme.objects.filter(accepting_applications=True)
        for f in ("gender", "date_of_birth", "phone", "address", "state_of_origin"):
            self.fields[f].required = False  # staff may capture partial paper forms and complete later

    def clean(self):
        d = super().clean()
        period, prog = d.get("period"), d.get("first_choice")
        if period and prog and not period.programmes.filter(pk=prog.pk).exists():
            self.add_error("first_choice", f"{prog} is not open in {period}.")
        email = (d.get("email") or "").strip().lower()
        if email:
            from apps.accounts.models import User
            if User.objects.filter(email__iexact=email).exists():
                self.add_error("email", "An account with this e-mail already exists. Search for the applicant instead.")
        return d


class OLevelForm(StyledModelForm):
    class Meta:
        model = OLevelResult
        fields = ["sitting", "exam_type", "exam_year", "exam_number", "subject", "grade"]
        widgets = {"exam_year": forms.NumberInput(attrs={"min": 1980, "max": 2100})}


OLevelFormSet = inlineformset_factory(Application, OLevelResult, form=OLevelForm, extra=9, max_num=18, can_delete=True)


class ApplicationDocumentForm(StyledModelForm):
    class Meta:
        model = ApplicationDocument
        fields = ["document_type", "file"]


class DecisionForm(StyledForm):
    decision = forms.ChoiceField(choices=[("admit", "Offer admission"), ("review", "Mark under review"), ("reject", "Not admitted")])
    programme = forms.ModelChoiceField(queryset=Programme.objects.all(), required=False,
                                       help_text="Programme to admit into (defaults to first choice)")
    note = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)


class ExemptionForm(StyledForm):
    reason = forms.CharField(max_length=255, help_text="e.g. Scholarship candidate, staff ward, community nomination")


class OfferOnBehalfForm(StyledForm):
    response = forms.ChoiceField(choices=[("accept", "Accept admission"), ("decline", "Decline admission")])
    matric_number = forms.CharField(required=False, help_text="Optional — generated automatically when empty")


class PeriodForm(StyledModelForm):
    class Meta:
        model = ApplicationPeriod
        fields = ["name", "session", "opens_on", "closes_on", "application_fee", "require_payment_before_submit",
                  "programmes", "instructions", "is_active"]
        widgets = {"programmes": forms.CheckboxSelectMultiple}
