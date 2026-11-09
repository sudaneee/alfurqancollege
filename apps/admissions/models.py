from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.validators import validate_document
from apps.students.models import DocumentType, PersonalInfo

OLEVEL_GRADES = ["A1", "B2", "B3", "C4", "C5", "C6", "D7", "E8", "F9"]
CREDIT_GRADES = {"A1", "B2", "B3", "C4", "C5", "C6"}
EXAM_TYPES = [("WAEC", "WAEC (WASSCE)"), ("NECO", "NECO (SSCE)"), ("NABTEB", "NABTEB"), ("GCE", "GCE O'Level"), ("NTC", "NTC"), ("OTHER", "Other")]


class ApplicationPeriod(models.Model):
    name = models.CharField(max_length=120, help_text="e.g. 2026/2027 Admission Exercise")
    session = models.ForeignKey("academics.AcademicSession", on_delete=models.PROTECT, related_name="application_periods",
                                help_text="Session admitted students will start in")
    opens_on = models.DateField()
    closes_on = models.DateField()
    application_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0,
                                          help_text="Set to 0 for free application forms")
    programmes = models.ManyToManyField("academics.Programme", related_name="application_periods",
                                        help_text="Programmes open for application in this period")
    instructions = models.TextField(blank=True)
    require_payment_before_submit = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-opens_on"]

    def __str__(self):
        return self.name

    def clean(self):
        if self.opens_on and self.closes_on and self.closes_on < self.opens_on:
            raise ValidationError("Closing date must be after the opening date.")

    def is_open(self, today=None):
        today = today or timezone.localdate()
        return self.is_active and self.opens_on <= today <= self.closes_on

    @classmethod
    def current(cls):
        today = timezone.localdate()
        return cls.objects.filter(is_active=True, opens_on__lte=today, closes_on__gte=today).first()


class Application(PersonalInfo):
    DRAFT, SUBMITTED, UNDER_REVIEW, ADMITTED, NOT_ADMITTED, WITHDRAWN = (
        "draft", "submitted", "under_review", "admitted", "not_admitted", "withdrawn")
    STATUS_CHOICES = [(DRAFT, "Draft"), (SUBMITTED, "Submitted"), (UNDER_REVIEW, "Under review"),
                      (ADMITTED, "Admitted"), (NOT_ADMITTED, "Not admitted"), (WITHDRAWN, "Withdrawn")]
    OFFER_PENDING, OFFER_ACCEPTED, OFFER_DECLINED = "pending", "accepted", "declined"
    OFFER_CHOICES = [(OFFER_PENDING, "Awaiting response"), (OFFER_ACCEPTED, "Accepted"), (OFFER_DECLINED, "Declined")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="applications")
    period = models.ForeignKey(ApplicationPeriod, on_delete=models.PROTECT, related_name="applications")
    application_number = models.CharField(max_length=40, unique=True, null=True, blank=True)
    first_choice = models.ForeignKey("academics.Programme", on_delete=models.PROTECT, related_name="first_choice_applications")
    second_choice = models.ForeignKey("academics.Programme", null=True, blank=True, on_delete=models.PROTECT,
                                      related_name="second_choice_applications")
    previous_institution = models.CharField(max_length=200, blank=True)
    other_qualifications = models.TextField(blank=True, help_text="e.g. JCHEW certificate, Environmental Health Assistant certificate")
    jamb_reg_number = models.CharField("JAMB/UTME number", max_length=30, blank=True)
    jamb_score = models.PositiveSmallIntegerField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT, db_index=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    fee_exempt = models.BooleanField(default=False)
    fee_exemption_reason = models.CharField(max_length=255, blank=True)
    fee_exempted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    admitted_programme = models.ForeignKey("academics.Programme", null=True, blank=True, on_delete=models.PROTECT,
                                           related_name="admitted_applications")
    decision_note = models.TextField(blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    offer_status = models.CharField(max_length=20, choices=OFFER_CHOICES, blank=True)
    offer_responded_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    is_sample = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["user", "period"], name="one_application_per_period")]

    def __str__(self):
        return f"{self.application_number or 'Draft'} — {self.display_name}"

    @property
    def is_editable_by_applicant(self):
        return self.status == self.DRAFT and self.period.is_open()

    @property
    def fee_invoice(self):
        return self.invoices.filter(purpose="application").exclude(status="cancelled").first()

    @property
    def fee_settled(self):
        if self.fee_exempt or self.period.application_fee <= 0:
            return True
        inv = self.fee_invoice
        return bool(inv and inv.status == "paid")

    @property
    def credit_count(self):
        return len({o.subject.lower() for o in self.olevels.all() if o.grade in CREDIT_GRADES})

    @property
    def is_converted(self):
        return hasattr(self, "student") and self.student is not None

    def missing_items(self):
        """Items preventing submission (used by both applicant and staff flows)."""
        missing = []
        for f in ("first_name", "last_name", "gender", "date_of_birth", "phone", "address", "state_of_origin"):
            if not getattr(self, f):
                missing.append(self._meta.get_field(f).verbose_name.capitalize())
        if self.olevels.count() < 5:
            missing.append("At least five O'Level subject results")
        uploaded = set(self.documents.values_list("document_type_id", flat=True))
        for dt in DocumentType.objects.filter(required_for_application=True):
            if dt.id not in uploaded:
                missing.append(f"Document: {dt.name}")
        if self.period.require_payment_before_submit and not self.fee_settled:
            missing.append("Application fee payment")
        return missing


class OLevelResult(models.Model):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="olevels")
    sitting = models.PositiveSmallIntegerField(default=1, choices=[(1, "First sitting"), (2, "Second sitting")])
    exam_type = models.CharField(max_length=10, choices=EXAM_TYPES, default="WAEC")
    exam_year = models.PositiveSmallIntegerField()
    exam_number = models.CharField(max_length=30, blank=True)
    subject = models.CharField(max_length=60)
    grade = models.CharField(max_length=3, choices=[(g, g) for g in OLEVEL_GRADES])

    class Meta:
        ordering = ["sitting", "subject"]
        constraints = [models.UniqueConstraint(fields=["application", "sitting", "subject"], name="unique_subject_per_sitting")]

    def __str__(self):
        return f"{self.subject}: {self.grade}"


class ApplicationDocument(models.Model):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="documents")
    document_type = models.ForeignKey(DocumentType, on_delete=models.PROTECT)
    file = models.FileField(upload_to="applications/%Y/", validators=[validate_document])
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["document_type__order"]
        constraints = [models.UniqueConstraint(fields=["application", "document_type"], name="one_doc_per_type")]


class ApplicationEvent(models.Model):
    """Complete, permanent application history."""

    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="events")
    action = models.CharField(max_length=60)
    note = models.TextField(blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    via_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class ApplicationSequence(models.Model):
    year = models.PositiveIntegerField(unique=True)
    last_serial = models.PositiveIntegerField(default=0)
