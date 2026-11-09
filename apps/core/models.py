from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


# --------------------------------------------------------------------------
# Permission registry
# --------------------------------------------------------------------------
# Every institutional capability is a Django permission attached to this
# anchor model. Roles are Django Groups, so the Super Administrator can grant
# or revoke any capability from the dashboard without code changes.
CAPABILITIES = [
    # System administration
    ("manage_settings", "System", "Manage institutional & system settings"),
    ("manage_users", "System", "Create, edit, deactivate users and reset passwords"),
    ("manage_roles", "System", "Configure roles and permissions"),
    ("view_audit_log", "System", "View audit logs"),
    ("manage_notifications", "System", "Manage notification templates & broadcast"),
    ("manage_website", "System", "Manage website content, news & announcements"),
    # Admissions
    ("view_applications", "Admissions", "View applications"),
    ("process_admissions", "Admissions", "Process applications & admission decisions"),
    ("manage_admission_settings", "Admissions", "Configure application periods & requirements"),
    ("grant_fee_exemption", "Admissions", "Grant application fee exemptions"),
    # Students
    ("view_students", "Students", "View student records"),
    ("manage_students", "Students", "Create & update student records"),
    ("change_student_status", "Students", "Change student status"),
    ("promote_students", "Students", "Promote students"),
    # Academics
    ("manage_academics", "Academics", "Manage sessions, programmes, departments & courses"),
    ("allocate_courses", "Academics", "Assign courses to lecturers"),
    # Course registration
    ("view_registrations", "Registration", "View course registrations"),
    ("manage_registrations", "Registration", "Register / add / drop courses on behalf of students"),
    ("approve_registrations", "Registration", "Approve course registrations"),
    ("override_registration_rules", "Registration", "Override registration deadlines & credit limits"),
    # Results
    ("upload_results", "Results", "Enter & upload results for allocated courses"),
    ("review_results", "Results", "Review results as Head of Department"),
    ("approve_results", "Results", "Give final approval to results"),
    ("publish_results", "Results", "Publish / unpublish results"),
    ("manage_all_results", "Results", "Edit any result, reopen & correct grades"),
    ("manage_grading", "Results", "Configure grading systems"),
    ("generate_transcripts", "Results", "Generate transcripts & result sheets"),
    # Bursary
    ("view_finance", "Bursary", "View invoices & payments"),
    ("record_payments", "Bursary", "Record offline payments"),
    ("verify_payments", "Bursary", "Verify payments"),
    ("manage_fees", "Bursary", "Configure fees, gateway & instalment rules"),
    ("manage_adjustments", "Bursary", "Grant discounts, scholarships & exemptions"),
    ("manage_refunds", "Bursary", "Record refunds"),
    # Reports
    ("view_reports", "Reports", "View institutional reports"),
    ("view_staff", "Reports", "View staff directory & reports"),
]


class PermissionAnchor(models.Model):
    """Holds the custom permission set (no rows are ever stored)."""

    class Meta:
        managed = True
        default_permissions = ()
        permissions = [(code, label) for code, _group, label in CAPABILITIES]


# --------------------------------------------------------------------------
# Institutional settings (singleton)
# --------------------------------------------------------------------------
class SiteSettings(models.Model):
    college_name = models.CharField(max_length=200, default="Alfurqan College of Health Sciences and Technology")
    short_name = models.CharField(max_length=40, default="Alfurqan College")
    motto = models.CharField(max_length=120, default="Character and Learning")
    logo = models.ImageField(upload_to="branding/", blank=True, help_text="Leave empty to use the official logo shipped with the platform.")
    website_url = models.URLField(default="https://alfurqancollege.com.ng/")

    address = models.TextField(blank=True)
    phone = models.CharField(max_length=60, blank=True)
    phone_alt = models.CharField(max_length=60, blank=True)
    email = models.EmailField(blank=True)
    office_hours = models.CharField(max_length=120, blank=True)
    map_embed_url = models.URLField(blank=True, max_length=600, help_text="Google Maps embed URL (optional).")
    facebook_url = models.URLField(blank=True)
    instagram_url = models.URLField(blank=True)
    x_url = models.URLField(blank=True, verbose_name="X / Twitter URL")

    # About content
    hero_title = models.CharField(max_length=160, default="Training competent health professionals for our communities")
    hero_subtitle = models.TextField(default="National Diploma and Diploma programmes in Public Health Technology, Nutrition and Dietetics, Health Information Management and Community Health.")
    intro = models.TextField(blank=True)
    history = models.TextField(blank=True)
    vision = models.TextField(blank=True)
    mission = models.TextField(blank=True)
    core_values = models.TextField(blank=True, help_text="One value per line. Use 'Title: description' for a description.")
    objectives = models.TextField(blank=True, help_text="One objective per line.")
    admission_overview = models.TextField(blank=True)
    general_requirements = models.TextField(blank=True, help_text="One requirement per line.")
    application_steps = models.TextField(blank=True, help_text="One step per line.")

    head_title = models.CharField(max_length=80, default="Provost")
    head_name = models.CharField(max_length=120, blank=True)
    head_message = models.TextField(blank=True)
    head_photo = models.ImageField(upload_to="branding/", blank=True)

    content_reviewed = models.BooleanField(
        default=False,
        help_text="Tick once all public text (vision, mission, welcome message, contact details) has been confirmed by the College.",
    )

    # Rules
    matric_number_format = models.CharField(
        max_length=80,
        default="AFC/{programme}/{yy}/{serial:04d}",
        help_text="Placeholders: {programme} programme code, {year} 4-digit session start year, {yy} 2-digit year, {serial} running number.",
    )
    application_number_format = models.CharField(max_length=80, default="AFC/APP/{year}/{serial:05d}")
    registration_requires_approval = models.BooleanField(default=True)
    max_document_size_mb = models.PositiveSmallIntegerField(default=5)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Institutional settings"
        verbose_name_plural = "Institutional settings"

    def __str__(self):
        return self.college_name

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Institutional settings cannot be deleted.")

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @staticmethod
    def _lines(text):
        return [line.strip() for line in (text or "").splitlines() if line.strip()]

    def core_values_list(self):
        out = []
        for line in self._lines(self.core_values):
            title, _, desc = line.partition(":")
            out.append({"title": title.strip(), "text": desc.strip()})
        return out

    def objectives_list(self):
        return self._lines(self.objectives)

    def requirements_list(self):
        return self._lines(self.general_requirements)

    def steps_list(self):
        return self._lines(self.application_steps)


# --------------------------------------------------------------------------
# Audit trail
# --------------------------------------------------------------------------
class AuditLog(models.Model):
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_actions")
    on_behalf_of = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_on_behalf",
        help_text="Set when a staff member acted for a student/applicant.",
    )
    action = models.CharField(max_length=60, db_index=True)
    module = models.CharField(max_length=40, blank=True, db_index=True)
    object_type = models.CharField(max_length=80, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    object_repr = models.CharField(max_length=255, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    note = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [models.Index(fields=["object_type", "object_id"])]

    def __str__(self):
        return f"{self.timestamp:%Y-%m-%d %H:%M} {self.actor} {self.action} {self.object_repr}"

    @property
    def via_staff(self):
        return bool(self.on_behalf_of_id and self.actor_id and self.on_behalf_of_id != self.actor_id)


# --------------------------------------------------------------------------
# Bulk import batches (preview → confirm workflow)
# --------------------------------------------------------------------------
class ImportBatch(models.Model):
    STATUS_PREVIEW = "preview"
    STATUS_APPLIED = "applied"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [(STATUS_PREVIEW, "Awaiting confirmation"), (STATUS_APPLIED, "Applied"), (STATUS_CANCELLED, "Cancelled")]

    kind = models.CharField(max_length=60, db_index=True)
    context = models.JSONField(default=dict, blank=True)
    file_name = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PREVIEW)
    rows = models.JSONField(default=list)
    summary = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="import_batches")
    created_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.kind} — {self.file_name}"

    @property
    def valid_count(self):
        return sum(1 for r in self.rows if not r.get("errors"))

    @property
    def error_count(self):
        return sum(1 for r in self.rows if r.get("errors"))
