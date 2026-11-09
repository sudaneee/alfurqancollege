from django import forms

from apps.academics.models import AcademicSession, Programme
from apps.core.forms import StyledForm, StyledModelForm

from .models import Adjustment, FeeCategory, FeeItem, GatewaySettings, Payment


class FeeCategoryForm(StyledModelForm):
    class Meta:
        model = FeeCategory
        fields = ["name", "code", "description", "order", "is_active"]


class FeeItemForm(StyledModelForm):
    class Meta:
        model = FeeItem
        fields = ["category", "name", "amount", "stage", "programmes", "session", "year_of_study", "term", "due_date",
                  "allow_instalments", "min_first_payment_percent", "is_active"]
        widgets = {"programmes": forms.CheckboxSelectMultiple}


class GatewaySettingsForm(StyledModelForm):
    class Meta:
        model = GatewaySettings
        fields = ["active_gateway", "online_payments_enabled", "pass_charges_to_payer", "instructions"]


class PayForm(StyledForm):
    amount = forms.DecimalField(min_value=1, decimal_places=2, max_digits=12, label="Amount to pay (₦)")


class OfflinePaymentForm(StyledForm):
    amount = forms.DecimalField(min_value=0.01, decimal_places=2, max_digits=12, label="Amount (₦)")
    method = forms.ChoiceField(choices=[c for c in Payment.METHOD_CHOICES if c[0] != "online"])
    reference = forms.CharField(max_length=80, label="Teller / transfer reference", required=False,
                                help_text="Bank teller number, transfer session ID or POS reference. Must be unique.")
    paid_on = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    note = forms.CharField(max_length=255, required=False)
    evidence = forms.FileField(required=False, help_text="Optional scan of the teller / receipt")
    verify = forms.BooleanField(required=False, initial=True, label="Mark as verified now")


class AdjustmentForm(StyledForm):
    kind = forms.ChoiceField(choices=Adjustment.KIND_CHOICES, label="Type")
    amount = forms.DecimalField(min_value=0.01, decimal_places=2, max_digits=12, label="Amount (₦)")
    reason = forms.CharField(max_length=255)
    sponsor = forms.CharField(max_length=150, required=False)


class RefundForm(StyledForm):
    amount = forms.DecimalField(min_value=0.01, decimal_places=2, max_digits=12, label="Refund amount (₦)")
    reason = forms.CharField(max_length=255)
    reference = forms.CharField(max_length=80, required=False)


class GenerateInvoicesForm(StyledForm):
    session = forms.ModelChoiceField(queryset=AcademicSession.objects.all())
    programme = forms.ModelChoiceField(queryset=Programme.objects.all(), required=False, help_text="Empty = all programmes")
    year = forms.IntegerField(min_value=1, max_value=6, required=False, label="Current year", help_text="Empty = all levels")
    stage = forms.ChoiceField(choices=FeeItem.STAGE_CHOICES, initial=FeeItem.STUDENT)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["session"].initial = AcademicSession.current()
