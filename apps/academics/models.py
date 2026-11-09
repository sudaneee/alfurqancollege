from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.core.validators import validate_document, validate_image

TERM_CHOICES = [(1, "First Semester"), (2, "Second Semester")]


class Department(models.Model):
    name = models.CharField(max_length=150, unique=True)
    code = models.CharField(max_length=20, unique=True)
    hod = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                            related_name="headed_departments", verbose_name="Head of Department")
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Programme(models.Model):
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="programmes")
    name = models.CharField(max_length=150, unique=True, help_text="e.g. Public Health Technology")
    code = models.CharField(max_length=10, unique=True, help_text="Short code used in matric numbers, e.g. PHT")
    slug = models.SlugField(max_length=160, unique=True, blank=True)
    award_title = models.CharField(max_length=200, help_text="e.g. National Diploma (ND) in Public Health Technology")
    regulatory_body = models.CharField(max_length=200, blank=True)
    curriculum_reference = models.CharField(max_length=255, blank=True, help_text="Source curriculum document and year")
    curriculum_file = models.FileField(upload_to="curricula/", blank=True, validators=[validate_document])

    duration_years = models.PositiveSmallIntegerField(default=2, validators=[MinValueValidator(1), MaxValueValidator(6)])
    semesters_per_year = models.PositiveSmallIntegerField(default=2, validators=[MinValueValidator(1), MaxValueValidator(3)])
    level_names = models.CharField(
        max_length=200, blank=True,
        help_text="Comma-separated names for each year, e.g. 'ND I, ND II' or 'Year One, Year Two, Year Three'.",
    )

    grading_scheme = models.ForeignKey("results.GradingScheme", on_delete=models.PROTECT, related_name="programmes")
    ca_max_score = models.DecimalField("Maximum CA score", max_digits=5, decimal_places=2, default=30)
    exam_max_score = models.DecimalField("Maximum exam score", max_digits=5, decimal_places=2, default=70)
    min_credit_units = models.PositiveSmallIntegerField("Minimum credit units per semester", default=0)
    max_credit_units = models.PositiveSmallIntegerField("Maximum credit units per semester", default=36)
    min_total_credits = models.PositiveSmallIntegerField("Minimum credit units for award", default=0)
    max_total_credits = models.PositiveSmallIntegerField("Maximum credit units for award", default=0,
                                                         help_text="0 means no upper limit.")

    summary = models.TextField(blank=True)
    goal = models.TextField(blank=True)
    objectives = models.TextField(blank=True, help_text="One objective per line.")
    entry_requirements = models.TextField(blank=True, help_text="One requirement per line.")
    structure_notes = models.TextField(blank=True, help_text="Programme structure & duration notes.")
    assessment_notes = models.TextField(blank=True)
    award_conditions = models.TextField(blank=True, help_text="One condition per line.")
    career_prospects = models.TextField(blank=True)
    image = models.ImageField(upload_to="programmes/", blank=True, validators=[validate_image])
    icon = models.CharField(max_length=40, default="bi-heart-pulse", help_text="Bootstrap icon class")

    is_published = models.BooleanField(default=True, help_text="Show on the public website")
    accepting_applications = models.BooleanField(default=True)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @property
    def total_semesters(self):
        return self.duration_years * self.semesters_per_year

    @property
    def max_score(self):
        return self.ca_max_score + self.exam_max_score

    @property
    def assessment_split(self):
        return f"{self.ca_max_score:g} / {self.exam_max_score:g}"

    def level_name(self, year):
        names = [n.strip() for n in (self.level_names or "").split(",") if n.strip()]
        if 1 <= year <= len(names):
            return names[year - 1]
        return f"Year {year}"

    def level_choices(self):
        return [(y, self.level_name(y)) for y in range(1, self.duration_years + 1)]

    def lines(self, field):
        return [line.strip() for line in (getattr(self, field) or "").splitlines() if line.strip()]

    @property
    def total_curriculum_credits(self):
        return self.courses.filter(is_active=True).aggregate(t=models.Sum("credit_units"))["t"] or 0


class PracticalRequirement(models.Model):
    KIND_CHOICES = [
        ("siwes", "SIWES (Industrial Work Experience)"),
        ("sce", "Supervised Clinical Experience"),
        ("scbe", "Supervised Community-Based Experience"),
        ("clinical", "Clinical Posting"),
        ("project", "Research Project"),
        ("licensing", "Professional / Licensing Examination"),
        ("other", "Other"),
    ]
    programme = models.ForeignKey(Programme, on_delete=models.CASCADE, related_name="practical_requirements")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    title = models.CharField(max_length=200)
    year = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Year of study")
    term = models.PositiveSmallIntegerField(null=True, blank=True, choices=TERM_CHOICES)
    timing = models.CharField(max_length=200, blank=True, help_text="When it takes place")
    duration = models.CharField(max_length=100, blank=True)
    assessment = models.TextField(blank=True)
    course = models.ForeignKey("Course", null=True, blank=True, on_delete=models.SET_NULL, related_name="practical_requirements")
    is_mandatory = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["programme", "order", "year"]

    def __str__(self):
        return f"{self.programme.code}: {self.title}"


class AcademicSession(models.Model):
    name = models.CharField(max_length=20, unique=True, help_text="e.g. 2025/2026")
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False)

    class Meta:
        ordering = ["-start_date"]

    def __str__(self):
        return self.name

    def clean(self):
        if self.start_date and self.end_date and self.end_date <= self.start_date:
            raise ValidationError("The session must end after it starts.")

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.is_current:
                AcademicSession.objects.exclude(pk=self.pk).update(is_current=False)
            super().save(*args, **kwargs)

    @property
    def start_year(self):
        return self.start_date.year

    @classmethod
    def current(cls):
        return cls.objects.filter(is_current=True).first()


class Semester(models.Model):
    session = models.ForeignKey(AcademicSession, on_delete=models.PROTECT, related_name="semesters")
    term = models.PositiveSmallIntegerField(choices=TERM_CHOICES)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    registration_opens = models.DateField(null=True, blank=True)
    registration_closes = models.DateField(null=True, blank=True, help_text="Course registration deadline")
    add_drop_closes = models.DateField(null=True, blank=True, help_text="Last day for add/drop after registration")
    results_entry_open = models.BooleanField(default=True)
    is_current = models.BooleanField(default=False)

    class Meta:
        ordering = ["-session__start_date", "-term"]
        constraints = [models.UniqueConstraint(fields=["session", "term"], name="unique_session_term")]

    def __str__(self):
        return f"{self.session.name} {self.get_term_display()}"

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.is_current:
                Semester.objects.exclude(pk=self.pk).update(is_current=False)
            super().save(*args, **kwargs)

    @classmethod
    def current(cls):
        return cls.objects.select_related("session").filter(is_current=True).first()

    @property
    def short(self):
        return f"{self.session.name} {'1st' if self.term == 1 else '2nd'} Sem."

    def registration_is_open(self, today=None):
        today = today or timezone.localdate()
        if self.registration_opens and today < self.registration_opens:
            return False
        if self.registration_closes and today > self.registration_closes:
            return False
        return True

    def add_drop_is_open(self, today=None):
        today = today or timezone.localdate()
        closes = self.add_drop_closes or self.registration_closes
        return not closes or today <= closes


class Course(models.Model):
    TYPE_CHOICES = [
        ("general", "General Studies"),
        ("foundation", "Foundation / Basic"),
        ("professional", "Professional"),
        ("siwes", "SIWES"),
        ("clinical", "Supervised Clinical Experience"),
        ("community", "Supervised Community-Based Experience"),
        ("project", "Project"),
        ("seminar", "Seminar"),
    ]
    programme = models.ForeignKey(Programme, on_delete=models.PROTECT, related_name="courses")
    code = models.CharField(max_length=20)
    title = models.CharField(max_length=200)
    credit_units = models.PositiveSmallIntegerField(validators=[MaxValueValidator(30)])
    lecture_hours = models.PositiveSmallIntegerField("L", null=True, blank=True)
    tutorial_hours = models.PositiveSmallIntegerField("T", null=True, blank=True)
    practical_hours = models.PositiveSmallIntegerField("P", null=True, blank=True)
    contact_hours = models.PositiveSmallIntegerField("Total contact hours", null=True, blank=True)
    year = models.PositiveSmallIntegerField("Year of study", validators=[MinValueValidator(1), MaxValueValidator(6)])
    term = models.PositiveSmallIntegerField(choices=TERM_CHOICES)
    course_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default="professional")
    is_compulsory = models.BooleanField(default=True)
    pass_fail_only = models.BooleanField(default=False, help_text="Graded pass/fail and excluded from GPA (e.g. SIWES where applicable).")
    prerequisites = models.ManyToManyField("self", symmetrical=False, blank=True, related_name="required_for")
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["programme", "year", "term", "code"]
        constraints = [
            models.UniqueConstraint(fields=["programme", "code", "year", "term"], name="unique_course_in_programme_slot"),
        ]

    def __str__(self):
        return f"{self.code} — {self.title}"

    @property
    def level_label(self):
        return self.programme.level_name(self.year)

    @property
    def slot_label(self):
        return f"{self.level_label}, {self.get_term_display()}"


class CourseAllocation(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="allocations")
    semester = models.ForeignKey(Semester, on_delete=models.CASCADE, related_name="allocations")
    lecturer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="course_allocations")
    is_coordinator = models.BooleanField(default=True, help_text="The coordinator uploads and submits the result.")
    allocated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    allocated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["semester", "course__code"]
        constraints = [models.UniqueConstraint(fields=["course", "semester", "lecturer"], name="unique_allocation")]

    def __str__(self):
        return f"{self.course.code} → {self.lecturer} ({self.semester.short})"


class CalendarEvent(models.Model):
    CATEGORY_CHOICES = [
        ("academic", "Academic"), ("registration", "Registration"), ("exam", "Examination"),
        ("holiday", "Holiday / Break"), ("admission", "Admission"), ("event", "Event"),
    ]
    session = models.ForeignKey(AcademicSession, on_delete=models.CASCADE, related_name="calendar_events")
    title = models.CharField(max_length=200)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="academic")
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    description = models.TextField(blank=True)
    is_public = models.BooleanField(default=True)

    class Meta:
        ordering = ["start_date"]

    def __str__(self):
        return self.title


class AcademicDocument(models.Model):
    """Downloadable documents for students (handbooks, curricula, timetables)."""

    title = models.CharField(max_length=200)
    file = models.FileField(upload_to="documents/", validators=[validate_document])
    programme = models.ForeignKey(Programme, null=True, blank=True, on_delete=models.CASCADE,
                                  help_text="Leave empty for all programmes.")
    description = models.CharField(max_length=255, blank=True)
    is_public = models.BooleanField(default=False, help_text="Also downloadable from the public website")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return self.title
