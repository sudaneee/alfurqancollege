from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class GradingScheme(models.Model):
    ALL_ATTEMPTS, LATEST_ATTEMPT = "all", "latest"
    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    source = models.CharField(max_length=255, blank=True, help_text="Curriculum document this scheme comes from")
    pass_mark = models.DecimalField(max_digits=5, decimal_places=2, help_text="Minimum total score to pass a course")
    max_points = models.DecimalField(max_digits=4, decimal_places=2, default=4)
    cgpa_policy = models.CharField(
        max_length=10, default=ALL_ATTEMPTS,
        choices=[(ALL_ATTEMPTS, "Count every attempt of a course"), (LATEST_ATTEMPT, "Count only the latest attempt")],
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def band_for(self, total):
        total = Decimal(total)
        for band in self.bands.all():
            if band.min_score <= total <= band.max_score:
                return band
        # Scores with decimals that fall between integer bands go to the lower band.
        lower = [b for b in self.bands.all() if b.min_score <= total]
        return max(lower, key=lambda b: b.min_score) if lower else None

    def classify(self, cgpa):
        if cgpa is None:
            return ""
        for c in self.classifications.all():
            if c.min_cgpa <= Decimal(cgpa) <= c.max_cgpa:
                return c.label
        return ""


class GradeBand(models.Model):
    scheme = models.ForeignKey(GradingScheme, on_delete=models.CASCADE, related_name="bands")
    min_score = models.DecimalField(max_digits=5, decimal_places=2)
    max_score = models.DecimalField(max_digits=5, decimal_places=2)
    letter = models.CharField(max_length=3)
    points = models.DecimalField(max_digits=4, decimal_places=2)
    remark = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ["-min_score"]

    def __str__(self):
        return f"{self.letter} ({self.min_score}-{self.max_score})"

    def clean(self):
        if self.min_score is not None and self.max_score is not None and self.min_score > self.max_score:
            raise ValidationError("Minimum score must not exceed maximum score.")


class ClassificationBand(models.Model):
    scheme = models.ForeignKey(GradingScheme, on_delete=models.CASCADE, related_name="classifications")
    min_cgpa = models.DecimalField(max_digits=4, decimal_places=2)
    max_cgpa = models.DecimalField(max_digits=4, decimal_places=2)
    label = models.CharField(max_length=60)

    class Meta:
        ordering = ["-min_cgpa"]

    def __str__(self):
        return f"{self.label} ({self.min_cgpa}-{self.max_cgpa})"


class ResultSheet(models.Model):
    DRAFT, SUBMITTED, HOD_APPROVED, APPROVED, PUBLISHED, RETURNED = (
        "draft", "submitted", "hod_approved", "approved", "published", "returned")
    STATUS_CHOICES = [
        (DRAFT, "Draft"), (SUBMITTED, "Submitted to HOD"), (HOD_APPROVED, "Reviewed by HOD"),
        (APPROVED, "Approved"), (PUBLISHED, "Published"), (RETURNED, "Returned for correction"),
    ]
    EDITABLE = (DRAFT, RETURNED)

    course = models.ForeignKey("academics.Course", on_delete=models.PROTECT, related_name="result_sheets")
    semester = models.ForeignKey("academics.Semester", on_delete=models.PROTECT, related_name="result_sheets")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT, db_index=True)
    ca_max = models.DecimalField(max_digits=5, decimal_places=2, help_text="Snapshot of programme CA weighting")
    exam_max = models.DecimalField(max_digits=5, decimal_places=2)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    submitted_at = models.DateTimeField(null=True, blank=True)
    hod_reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    hod_reviewed_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    published_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-semester__session__start_date", "course__code"]
        constraints = [models.UniqueConstraint(fields=["course", "semester"], name="one_sheet_per_course_semester")]

    def __str__(self):
        return f"{self.course.code} — {self.semester}"

    @property
    def is_editable(self):
        return self.status in self.EDITABLE

    @property
    def scheme(self):
        return self.course.programme.grading_scheme


class Score(models.Model):
    sheet = models.ForeignKey(ResultSheet, on_delete=models.CASCADE, related_name="scores")
    student = models.ForeignKey("students.Student", on_delete=models.PROTECT, related_name="scores")
    registered_course = models.OneToOneField("registration.RegisteredCourse", null=True, blank=True,
                                             on_delete=models.SET_NULL, related_name="score")
    ca = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    exam = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    total = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    grade = models.CharField(max_length=3, blank=True)
    points = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    credit_units = models.PositiveSmallIntegerField()
    remark = models.CharField(max_length=60, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["student__matric_number"]
        constraints = [models.UniqueConstraint(fields=["sheet", "student"], name="one_score_per_student_sheet")]

    def __str__(self):
        return f"{self.student.matric_number} {self.sheet.course.code}: {self.total}"

    @property
    def is_complete(self):
        return self.ca is not None and self.exam is not None

    @property
    def passed(self):
        return self.total is not None and self.total >= self.sheet.scheme.pass_mark

    def compute(self):
        """Derive total, grade and grade points from CA + exam using the programme scheme."""
        if self.ca is None or self.exam is None:
            self.total, self.grade, self.points, self.remark = None, "", None, "Incomplete"
            return
        self.total = Decimal(self.ca) + Decimal(self.exam)
        band = self.sheet.scheme.band_for(self.total)
        if self.sheet.course.pass_fail_only:
            self.grade = "P" if self.passed else "F"
            self.points = None
            self.remark = "Pass" if self.passed else "Fail"
            return
        self.grade = band.letter if band else ""
        self.points = band.points if band else Decimal("0")
        self.remark = (band.remark if band and band.remark else ("Pass" if self.passed else "Fail"))


class ResultSheetEvent(models.Model):
    sheet = models.ForeignKey(ResultSheet, on_delete=models.CASCADE, related_name="events")
    action = models.CharField(max_length=40)
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20, blank=True)
    note = models.TextField(blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
