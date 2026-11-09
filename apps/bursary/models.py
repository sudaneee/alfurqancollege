from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Sum

from apps.core.validators import validate_document

ZERO = Decimal("0.00")


class FeeCategory(models.Model):
    name = models.CharField(max_length=120, unique=True)
    code = models.SlugField(max_length=40, unique=True)
    description = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]
        verbose_name_plural = "Fee categories"

    def __str__(self):
        return self.name


class FeeItem(models.Model):
    """A configurable charge. Empty programme/session/year means 'applies to all'."""

    STUDENT, ACCEPTANCE = "student", "acceptance"
    STAGE_CHOICES = [(STUDENT, "Session fees (students)"), (ACCEPTANCE, "Acceptance of admission")]

    category = models.ForeignKey(FeeCategory, on_delete=models.PROTECT, related_name="items")
    name = models.CharField(max_length=150)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    stage = models.CharField(max_length=20, choices=STAGE_CHOICES, default=STUDENT)
    programmes = models.ManyToManyField("academics.Programme", blank=True, related_name="fee_items",
                                        help_text="Leave empty to apply to all programmes")
    session = models.ForeignKey("academics.AcademicSession", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="fee_items", help_text="Leave empty to apply to every session")
    year_of_study = models.PositiveSmallIntegerField(null=True, blank=True,
                                                     help_text="Leave empty for all levels; 1 for first-year only")
    term = models.PositiveSmallIntegerField(null=True, blank=True, choices=[(1, "First Semester"), (2, "Second Semester")],
                                            help_text="Leave empty for once-per-session charges")
    due_date = models.DateField(null=True, blank=True)
    allow_instalments = models.BooleanField(default=True)
    min_first_payment_percent = models.PositiveSmallIntegerField(
        default=0, validators=[MaxValueValidator(100)],
        help_text="Minimum percentage of the invoice payable in the first instalment (0 = any amount)",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["category__order", "name"]

    def __str__(self):
        return f"{self.name} — ₦{self.amount:,.2f}"

    def applies_to(self, programme, session, year):
        if not self.is_active:
            return False
        if self.session_id and self.session_id != session.id:
            return False
        if self.year_of_study and self.year_of_study != year:
            return False
        progs = list(self.programmes.all())
        return not progs or programme in progs

    @property
    def scope_label(self):
        progs = ", ".join(p.code for p in self.programmes.all()) or "All programmes"
        level = f"Year {self.year_of_study}" if self.year_of_study else "All levels"
        sess = self.session.name if self.session_id else "Every session"
        return f"{progs} · {level} · {sess}"


class Invoice(models.Model):
    UNPAID, PART_PAID, PAID, CANCELLED = "unpaid", "part_paid", "paid", "cancelled"
    STATUS_CHOICES = [(UNPAID, "Unpaid"), (PART_PAID, "Part paid"), (PAID, "Paid"), (CANCELLED, "Cancelled")]
    PURPOSE_CHOICES = [("application", "Application form"), ("acceptance", "Acceptance fee"),
                       ("fees", "Session fees"), ("other", "Other")]

    number = models.CharField(max_length=30, unique=True)
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES, default="fees")
    student = models.ForeignKey("students.Student", null=True, blank=True, on_delete=models.PROTECT, related_name="invoices")
    application = models.ForeignKey("admissions.Application", null=True, blank=True, on_delete=models.PROTECT, related_name="invoices")
    session = models.ForeignKey("academics.AcademicSession", null=True, blank=True, on_delete=models.PROTECT, related_name="invoices")
    description = models.CharField(max_length=255)
    gross_amount = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    adjustments_total = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=UNPAID, db_index=True)
    allow_instalments = models.BooleanField(default=True)
    min_first_payment = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    due_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    is_sample = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=models.Q(student__isnull=False) | models.Q(application__isnull=False),
                                   name="invoice_has_payer"),
        ]

    def __str__(self):
        return f"{self.number} — {self.description}"

    @property
    def net_amount(self):
        return max(ZERO, self.gross_amount - self.adjustments_total)

    @property
    def balance(self):
        return max(ZERO, self.net_amount - self.amount_paid)

    @property
    def payer_name(self):
        if self.student_id:
            return self.student.display_name
        return self.application.display_name if self.application_id else ""

    @property
    def payer_reference(self):
        if self.student_id:
            return self.student.matric_number
        return self.application.application_number or f"Application #{self.application_id}" if self.application_id else ""

    @property
    def payer_user(self):
        if self.student_id:
            return self.student.user
        return self.application.user if self.application_id else None

    def minimum_payment(self):
        """Smallest amount accepted for the next payment under the instalment policy."""
        bal = self.balance
        if bal <= 0:
            return ZERO
        if not self.allow_instalments:
            return bal
        if self.amount_paid <= 0 and self.min_first_payment > 0:
            return min(bal, self.min_first_payment)
        return min(bal, Decimal("1.00"))

    def recalculate(self, save=True):
        self.gross_amount = self.lines.aggregate(t=Sum("amount"))["t"] or ZERO
        self.adjustments_total = self.adjustments.aggregate(t=Sum("amount"))["t"] or ZERO
        paid = self.payments.filter(status=Payment.SUCCESSFUL).aggregate(t=Sum("amount"))["t"] or ZERO
        refunded = Refund.objects.filter(payment__invoice=self).aggregate(t=Sum("amount"))["t"] or ZERO
        self.amount_paid = paid - refunded
        if self.status != self.CANCELLED:
            if self.net_amount <= 0 or self.amount_paid >= self.net_amount:
                self.status = self.PAID
            elif self.amount_paid > 0:
                self.status = self.PART_PAID
            else:
                self.status = self.UNPAID
        if save:
            self.save(update_fields=["gross_amount", "adjustments_total", "amount_paid", "status"])


class InvoiceLine(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    fee_item = models.ForeignKey(FeeItem, null=True, blank=True, on_delete=models.PROTECT)
    category = models.ForeignKey(FeeCategory, null=True, blank=True, on_delete=models.PROTECT)
    description = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.description}: {self.amount}"


class Adjustment(models.Model):
    """Discounts, scholarships and exemptions reduce what is owed (never deleted, only reversed)."""

    KIND_CHOICES = [("discount", "Discount"), ("scholarship", "Scholarship"), ("exemption", "Exemption / waiver")]
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="adjustments")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=255)
    sponsor = models.CharField(max_length=150, blank=True, help_text="Scholarship sponsor, where applicable")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} {self.amount} on {self.invoice.number}"


class Payment(models.Model):
    PENDING, SUCCESSFUL, FAILED, REVERSED = "pending", "successful", "failed", "reversed"
    STATUS_CHOICES = [(PENDING, "Pending"), (SUCCESSFUL, "Successful"), (FAILED, "Failed"), (REVERSED, "Reversed")]
    METHOD_CHOICES = [("online", "Online (gateway)"), ("bank_transfer", "Bank transfer"), ("bank_deposit", "Bank deposit"),
                      ("pos", "POS"), ("cash", "Cash")]

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    method = models.CharField(max_length=20, choices=METHOD_CHOICES)
    reference = models.CharField(max_length=80, unique=True, help_text="Gateway or bank reference")
    gateway = models.CharField(max_length=30, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING, db_index=True)
    receipt_number = models.CharField(max_length=30, unique=True, null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    payer_note = models.CharField(max_length=255, blank=True)
    evidence = models.FileField(upload_to="payments/evidence/%Y/", blank=True, validators=[validate_document])
    initiated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    verified_at = models.DateTimeField(null=True, blank=True)
    gateway_response = models.JSONField(default=dict, blank=True)
    is_sample = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.reference} — ₦{self.amount:,.2f} ({self.get_status_display()})"

    @property
    def via_staff(self):
        payer = self.invoice.payer_user
        return bool(self.initiated_by_id and payer and self.initiated_by_id != payer.id)


class Refund(models.Model):
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="refunds")
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    reason = models.CharField(max_length=255)
    reference = models.CharField(max_length=80, blank=True)
    processed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    processed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-processed_at"]

    def clean(self):
        if self.payment_id and self.amount:
            already = self.payment.refunds.exclude(pk=self.pk).aggregate(t=Sum("amount"))["t"] or ZERO
            if already + self.amount > self.payment.amount:
                raise ValidationError("Total refunds cannot exceed the payment amount.")


class TransactionLog(models.Model):
    """Every gateway interaction (initiate, verify, webhook) for traceability."""

    payment = models.ForeignKey(Payment, null=True, blank=True, on_delete=models.SET_NULL, related_name="logs")
    reference = models.CharField(max_length=80, db_index=True)
    gateway = models.CharField(max_length=30)
    event = models.CharField(max_length=40)
    success = models.BooleanField(default=False)
    payload = models.JSONField(default=dict, blank=True)
    message = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class GatewaySettings(models.Model):
    """Non-secret gateway configuration (API secrets live in environment variables)."""

    GATEWAY_CHOICES = [("paystack", "Paystack"), ("flutterwave", "Flutterwave"), ("sandbox", "Sandbox (testing only)")]
    active_gateway = models.CharField(max_length=20, choices=GATEWAY_CHOICES, default="sandbox")
    online_payments_enabled = models.BooleanField(default=True)
    pass_charges_to_payer = models.BooleanField(default=False)
    instructions = models.TextField(blank=True, help_text="Bank details / offline payment instructions shown to students")

    class Meta:
        verbose_name = "Payment gateway settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class NumberSequence(models.Model):
    key = models.CharField(max_length=40, unique=True)
    last = models.PositiveIntegerField(default=0)
