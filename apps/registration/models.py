from django.conf import settings
from django.db import models


class CourseRegistration(models.Model):
    DRAFT, SUBMITTED, APPROVED, REJECTED = "draft", "submitted", "approved", "rejected"
    STATUS_CHOICES = [(DRAFT, "Draft"), (SUBMITTED, "Submitted"), (APPROVED, "Approved"), (REJECTED, "Returned")]

    student = models.ForeignKey("students.Student", on_delete=models.PROTECT, related_name="registrations")
    semester = models.ForeignKey("academics.Semester", on_delete=models.PROTECT, related_name="registrations")
    year_of_study = models.PositiveSmallIntegerField(help_text="Student's level when registering")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT, db_index=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-semester__session__start_date", "-semester__term"]
        constraints = [models.UniqueConstraint(fields=["student", "semester"], name="one_registration_per_semester")]

    def __str__(self):
        return f"{self.student.matric_number} — {self.semester}"

    @property
    def level_label(self):
        return self.student.programme.level_name(self.year_of_study)

    @property
    def total_units(self):
        return sum(i.course.credit_units for i in self.items.select_related("course"))


class RegisteredCourse(models.Model):
    registration = models.ForeignKey(CourseRegistration, on_delete=models.CASCADE, related_name="items")
    course = models.ForeignKey("academics.Course", on_delete=models.PROTECT, related_name="registrations")
    is_carryover = models.BooleanField(default=False)
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["course__code"]
        constraints = [models.UniqueConstraint(fields=["registration", "course"], name="no_duplicate_course_registration")]

    def __str__(self):
        return f"{self.registration.student.matric_number}: {self.course.code}"

    @property
    def via_staff(self):
        return self.added_by_id and self.added_by_id != self.registration.student.user_id


class RegistrationEvent(models.Model):
    """Course registration history: add, drop, submit, approve, return."""

    registration = models.ForeignKey(CourseRegistration, on_delete=models.CASCADE, related_name="events")
    action = models.CharField(max_length=30)
    course = models.ForeignKey("academics.Course", null=True, blank=True, on_delete=models.SET_NULL)
    note = models.CharField(max_length=255, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    via_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
