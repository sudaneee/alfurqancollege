from django import forms

from .models import SiteSettings


class StyledFormMixin:
    """Applies the design-system classes to every widget and flags wide fields."""

    wide_fields = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            w = field.widget
            if isinstance(w, (forms.CheckboxInput,)):
                w.attrs.setdefault("class", "form-check-input")
                w.attrs.setdefault("role", "switch")
            elif isinstance(w, (forms.CheckboxSelectMultiple, forms.RadioSelect)):
                field.wide = True
            elif isinstance(w, (forms.Select, forms.SelectMultiple)):
                w.attrs.setdefault("class", "form-select")
            else:
                w.attrs.setdefault("class", "form-control")
            if isinstance(w, forms.Textarea):
                w.attrs.setdefault("rows", 3)
                field.wide = True
            if isinstance(w, forms.SelectMultiple) and not isinstance(w, forms.CheckboxSelectMultiple):
                w.attrs.setdefault("size", 6)
            if isinstance(w, forms.DateInput):
                w.input_type = "date"
                w.format = "%Y-%m-%d"
            if name in self.wide_fields:
                field.wide = True
            if field.required and not isinstance(w, (forms.CheckboxSelectMultiple, forms.FileInput)):
                w.attrs.setdefault("required", True)


class StyledForm(StyledFormMixin, forms.Form):
    pass


class StyledModelForm(StyledFormMixin, forms.ModelForm):
    pass


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, attrs=None):
        super().__init__(attrs, format="%Y-%m-%d")


class SiteSettingsForm(StyledModelForm):
    class Meta:
        model = SiteSettings
        exclude = ["updated_at"]

    SECTIONS = [
        ("Identity", "bi-bank", ["college_name", "short_name", "motto", "logo", "website_url"]),
        ("Contact details", "bi-telephone", ["address", "phone", "phone_alt", "email", "office_hours", "map_embed_url",
                                              "facebook_url", "instagram_url", "x_url"]),
        ("Homepage & About", "bi-file-richtext", ["hero_title", "hero_subtitle", "intro", "history", "vision", "mission",
                                                   "core_values", "objectives"]),
        ("Head of institution", "bi-person-badge", ["head_title", "head_name", "head_message", "head_photo"]),
        ("Admissions page", "bi-mortarboard", ["admission_overview", "general_requirements", "application_steps"]),
        ("Rules & numbering", "bi-sliders", ["matric_number_format", "application_number_format",
                                             "registration_requires_approval", "max_document_size_mb", "content_reviewed"]),
    ]

    def sections(self):
        for title, icon, names in self.SECTIONS:
            yield title, icon, [self[n] for n in names]


class ReasonForm(StyledForm):
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)
