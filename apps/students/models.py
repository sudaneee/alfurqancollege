from django.conf import settings
from django.db import models

from apps.core.validators import validate_document, validate_image

GENDER_CHOICES = [("M", "Male"), ("F", "Female")]
NIGERIAN_STATES = [
    "Abia", "Adamawa", "Akwa Ibom", "Anambra", "Bauchi", "Bayelsa", "Benue", "Borno", "Cross River", "Delta",
    "Ebonyi", "Edo", "Ekiti", "Enugu", "FCT", "Gombe", "Imo", "Jigawa", "Kaduna", "Kano", "Katsina", "Kebbi",
    "Kogi", "Kwara", "Lagos", "Nasarawa", "Niger", "Ogun", "Ondo", "Osun", "Oyo", "Plateau", "Rivers", "Sokoto",
    "Taraba", "Yobe", "Zamfara",
]
STATE_CHOICES = [(s, s) for s in NIGERIAN_STATES] + [("Non-Nigerian", "Non-Nigerian")]


class StudentStatus(models.Model):
    """Configurable student statuses (Admitted, Active, Suspended, ...)."""

    name = models.CharField(max_length=60, unique=True)
    code = models.SlugField(max_length=30, unique=True)
    description = models.CharField(max_length=255, blank=True)
    can_register_courses = models.BooleanField(default=False)
    can_login = models.BooleanField(default=True)
    counts_as_enrolled = models.BooleanField(default=False, help_text="Included in current student population")
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]
        verbose_name_plural = "Student statuses"

    def __str__(self):
        return self.name

    @classmethod
    def get(cls, code):
        return cls.objects.filter(code=code).first()


class DocumentType(models.Model):
    name = models.CharField(max_length=120, unique=True)
    description = models.CharField(max_length=255, blank=True)
    required_for_application = models.BooleanField(default=False)
    required_for_students = models.BooleanField(default=False)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class PersonalInfo(models.Model):
    """Biodata shared by applications and student records."""

    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField("Surname", max_length=100)
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField("Residential address", blank=True)
    state_of_origin = models.CharField(max_length=40, choices=STATE_CHOICES, blank=True)
    lga = models.CharField("Local Government Area", max_length=80, blank=True)
    nationality = models.CharField(max_length=60, default="Nigerian", blank=True)
    next_of_kin_name = models.CharField(max_length=150, blank=True)
    next_of_kin_relationship = models.CharField(max_length=60, blank=True)
    next_of_kin_phone = models.CharField(max_length=30, blank=True)
    next_of_kin_address = models.TextField(blank=True)
    guardian_name = models.CharField("Parent / guardian name", max_length=150, blank=True)
    guardian_phone = models.CharField("Parent / guardian phone", max_length=30, blank=True)
    guardian_address = models.TextField("Parent / guardian address", blank=True)

    class Meta:
        abstract = True

    @property
    def full_name(self):
        return " ".join(p for p in [self.last_name.upper() if self.last_name else "", self.first_name, self.middle_name] if p)

    @property
    def display_name(self):
        return " ".join(p for p in [self.first_name, self.middle_name, self.last_name] if p)


class Student(PersonalInfo):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="student")
    matric_number = models.CharField(max_length=40, unique=True)
    application = models.OneToOneField("admissions.Application", null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="student")
    programme = models.ForeignKey("academics.Programme", on_delete=models.PROTECT, related_name="students")
    entry_session = models.ForeignKey("academics.AcademicSession", on_delete=models.PROTECT, related_name="admitted_students",
                                      verbose_name="Session of admission")
    current_year = models.PositiveSmallIntegerField("Current level (year)", default=1)
    current_term = models.PositiveSmallIntegerField("Current semester", default=1, choices=[(1, "First"), (2, "Second")])
    status = models.ForeignKey(StudentStatus, on_delete=models.PROTECT, related_name="students")
    previous_education = models.TextField("Previous educational qualifications", blank=True)
    photo = models.ImageField(upload_to="students/photos/", blank=True, validators=[validate_image])
    date_admitted = models.DateField(null=True, blank=True)
    graduation_date = models.DateField(null=True, blank=True)
    is_sample = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Fields a student may edit personally (staff can edit everything).
    SELF_EDITABLE = ["phone", "email", "address", "next_of_kin_name", "next_of_kin_relationship", "next_of_kin_phone",
                     "next_of_kin_address", "guardian_name", "guardian_phone", "guardian_address"]

    class Meta:
        ordering = ["matric_number"]
        indexes = [models.Index(fields=["programme", "current_year"])]

    def __str__(self):
        return f"{self.matric_number} — {self.display_name}"

    @property
    def department(self):
        return self.programme.department

    @property
    def level_label(self):
        return self.programme.level_name(self.current_year)

    @property
    def is_final_year(self):
        return self.current_year >= self.programme.duration_years


class StudentDocument(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="documents")
    document_type = models.ForeignKey(DocumentType, on_delete=models.PROTECT)
    file = models.FileField(upload_to="students/documents/%Y/", validators=[validate_document])
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    is_verified = models.BooleanField(default=False)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"{self.document_type} — {self.student.matric_number}"

    @property
    def via_staff(self):
        return self.uploaded_by_id and self.uploaded_by_id != self.student.user_id


class StudentStatusHistory(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="status_history")
    from_status = models.ForeignKey(StudentStatus, null=True, on_delete=models.PROTECT, related_name="+")
    to_status = models.ForeignKey(StudentStatus, on_delete=models.PROTECT, related_name="+")
    reason = models.TextField(blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-changed_at"]


class AcademicHistory(models.Model):
    """Records each level change (admission, promotion, repeat, graduation)."""

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="academic_history")
    session = models.ForeignKey("academics.AcademicSession", on_delete=models.PROTECT)
    event = models.CharField(max_length=30, choices=[("admitted", "Admitted"), ("promoted", "Promoted"),
                                                     ("repeated", "Repeating level"), ("graduated", "Graduated"),
                                                     ("changed", "Programme / level changed")])
    from_year = models.PositiveSmallIntegerField(null=True, blank=True)
    to_year = models.PositiveSmallIntegerField(null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-recorded_at"]


class MatricSequence(models.Model):
    programme = models.ForeignKey("academics.Programme", on_delete=models.CASCADE)
    session = models.ForeignKey("academics.AcademicSession", on_delete=models.CASCADE)
    last_serial = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["programme", "session"], name="unique_matric_seq")]
