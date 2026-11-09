from django.contrib.auth.models import AbstractUser, Group
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower


class User(AbstractUser):
    """One identity for every person on the platform.

    `user_type` decides which portal the account belongs to; roles (Django
    Groups) and permissions decide what a staff member may do.
    """

    APPLICANT = "applicant"
    STUDENT = "student"
    STAFF = "staff"
    TYPE_CHOICES = [(APPLICANT, "Applicant"), (STUDENT, "Student"), (STAFF, "Staff")]

    user_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=APPLICANT, db_index=True)
    other_names = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    must_change_password = models.BooleanField(default=False)
    is_sample = models.BooleanField(default=False, help_text="Demonstration record (not real institutional data).")

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower("email"), condition=~Q(email=""), name="unique_nonblank_email_ci"),
        ]
        ordering = ["first_name", "last_name"]

    def __str__(self):
        return self.get_full_name() or self.username

    def get_full_name(self):
        parts = [self.first_name, self.other_names, self.last_name]
        return " ".join(p for p in parts if p).strip()

    @property
    def is_super_admin(self):
        return self.is_superuser or self.groups.filter(name="Super Administrator").exists()

    @property
    def role_names(self):
        if self.is_superuser:
            return ["Super Administrator"]
        return [g.name for g in self.groups.all()]

    @property
    def portal_home(self):
        if self.user_type == self.STAFF or self.is_superuser:
            return "core:dashboard"
        if self.user_type == self.STUDENT:
            return "students:portal_dashboard"
        return "admissions:portal_dashboard"


class RoleProfile(models.Model):
    """Extra metadata for a role (Django Group)."""

    group = models.OneToOneField(Group, on_delete=models.CASCADE, related_name="profile")
    description = models.TextField(blank=True)
    is_system = models.BooleanField(default=False, help_text="Built-in role. It can be edited but not deleted.")
    dashboard = models.CharField(
        max_length=30, blank=True,
        choices=[("superadmin", "Super Admin"), ("admin", "Administrator"), ("academic", "Academic Officer"),
                 ("admission", "Admission Officer"), ("bursary", "Bursary Officer"), ("hod", "Head of Department"),
                 ("lecturer", "Lecturer")],
    )

    def __str__(self):
        return self.group.name


class StaffProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="staff_profile")
    staff_id = models.CharField(max_length=40, unique=True)
    department = models.ForeignKey("academics.Department", null=True, blank=True, on_delete=models.SET_NULL, related_name="staff")
    designation = models.CharField(max_length=120, blank=True)
    qualification = models.CharField(max_length=200, blank=True)
    date_employed = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["user__first_name"]

    def __str__(self):
        return f"{self.user.get_full_name()} ({self.staff_id})"
