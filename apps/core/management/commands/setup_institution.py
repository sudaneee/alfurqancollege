"""Load the official institutional configuration.

    python manage.py setup_institution

Idempotent: safe to run again; it never overwrites values an administrator
has already changed (records are created only if missing).
"""
import shutil
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.core.files import File
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.academics import curricula
from apps.academics.models import AcademicDocument, Course, Department, PracticalRequirement, Programme
from apps.accounts.models import RoleProfile
from apps.bursary.models import FeeCategory, FeeItem, GatewaySettings
from apps.core.models import CAPABILITIES, SiteSettings
from apps.notifications.models import NotificationTemplate
from apps.results.models import ClassificationBand, GradeBand, GradingScheme
from apps.students.models import DocumentType, StudentStatus
from apps.website.models import HeroSlide, Highlight

ALL = [c for c, _g, _l in CAPABILITIES]

ROLES = {
    "Super Administrator": ("superadmin", "Complete control of the platform, including roles, permissions and overrides.", ALL),
    "Administrator": ("admin", "Day-to-day administration across modules, without changing roles or overriding results.",
                      [c for c in ALL if c not in ("manage_roles", "manage_all_results", "override_registration_rules")]),
    "Academic Officer": ("academic", "Academic sessions, courses, registration, progression and result administration.",
                         ["view_students", "manage_students", "change_student_status", "promote_students", "manage_academics",
                          "allocate_courses", "view_registrations", "manage_registrations", "approve_registrations",
                          "override_registration_rules", "approve_results", "publish_results", "generate_transcripts",
                          "manage_grading", "view_reports"]),
    "Admission Officer": ("admission", "Applications, applicants, admission decisions and statistics.",
                          ["view_applications", "process_admissions", "manage_admission_settings", "grant_fee_exemption",
                           "view_students", "view_reports"]),
    "Bursary Officer": ("bursary", "Fees, invoices, payment recording and verification, financial reports.",
                        ["view_finance", "record_payments", "verify_payments", "manage_fees", "manage_adjustments",
                         "manage_refunds", "view_students", "view_reports"]),
    "Head of Department": ("hod", "Departmental students, course allocation and result review.",
                           ["view_students", "allocate_courses", "view_registrations", "manage_registrations",
                            "approve_registrations", "upload_results", "review_results", "generate_transcripts", "view_reports"]),
    "Lecturer": ("lecturer", "Allocated courses, score sheets and result upload.", ["upload_results", "view_registrations"]),
}

STATUSES = [
    ("Applicant", "applicant", "Record created before acceptance", False, True, False),
    ("Admitted", "admitted", "Accepted admission; not yet registered", True, True, True),
    ("Active", "active", "Registered and studying", True, True, True),
    ("Suspended", "suspended", "Temporarily barred from academic activities", False, True, False),
    ("Withdrawn", "withdrawn", "Left the programme", False, False, False),
    ("Graduated", "graduated", "Completed the programme", False, True, False),
]

DOC_TYPES = [
    ("O'Level result (first sitting)", True, True), ("O'Level result (second sitting)", False, False),
    ("Birth certificate / declaration of age", True, True), ("Passport photograph", True, True),
    ("Local Government identification", False, True), ("JAMB/UTME result", False, False),
    ("Other qualification certificate", False, False),
]

TEMPLATES = [
    ("application_submitted", "Application submitted", "Application {number} received",
     "Dear {name},\n\nYour application ({number}) for {programme} has been submitted successfully. We will notify you of the decision.\n\n{college}",
     "{name}, {number}, {programme}"),
    ("admission_offered", "Admission offered", "Congratulations — admission offered",
     "Dear {name},\n\nYou have been offered provisional admission into {programme}. Sign in to the Application Portal to accept the offer and download your admission letter.\n\n{college}",
     "{name}, {number}, {programme}"),
    ("admission_not_offered", "Admission not offered", "Update on your application {number}",
     "Dear {name},\n\nWe regret that we are unable to offer you admission in this exercise.\n\n{college}", "{name}, {number}"),
    ("admission_accepted", "Admission accepted", "Welcome to Alfurqan College",
     "Dear {name},\n\nYour admission into {programme} is confirmed. Your matric number is {matric}. Use it to sign in to the Student Portal.",
     "{name}, {matric}, {programme}"),
    ("payment_received", "Payment confirmation", "Payment of {amount} received",
     "Dear {name},\n\nWe have received your payment of {amount} for {description}. Receipt: {receipt}. Reference: {reference}. Outstanding balance: {balance}.",
     "{name}, {amount}, {description}, {receipt}, {reference}, {balance}"),
    ("registration_reviewed", "Course registration reviewed", "Course registration {status}",
     "Dear {name},\n\nYour course registration for {semester} is now: {status}. {note}", "{name}, {semester}, {status}, {note}"),
    ("result_published", "Result published", "New result published: {course}",
     "Dear {name},\n\nYour result for {course} ({semester}) has been published. Sign in to the Student Portal to view it.",
     "{name}, {course}, {semester}"),
    ("result_submitted", "Result awaiting HOD review", "Result submitted: {course}",
     "{course} ({semester}) has been submitted and is awaiting your review.", "{course}, {semester}"),
    ("result_returned", "Result returned for correction", "Result returned: {course}",
     "Your result for {course} was returned for correction: {note}", "{course}, {note}"),
    ("course_allocated", "Course allocated", "Course allocated: {course}",
     "You have been allocated {course} for {semester}. Open 'My courses' in the Staff Portal.", "{course}, {semester}"),
    ("contact_message", "New website enquiry", "New enquiry: {subject}", "New message from {sender}: {subject}", "{subject}, {sender}"),
]


class Command(BaseCommand):
    help = "Load the official institutional configuration (roles, programmes, curricula, grading, fees)."

    @transaction.atomic
    def handle(self, *args, **opts):
        self.roles()
        schemes = self.grading()
        self.programmes(schemes)
        self.fees()
        self.misc()
        self.stdout.write(self.style.SUCCESS("Institutional configuration loaded."))
        self.stdout.write("Source document notes requiring confirmation:")
        for n in curricula.SOURCE_NOTES:
            self.stdout.write(f"  - {n}")

    def roles(self):
        perms = {p.codename: p for p in Permission.objects.filter(content_type__app_label="core")}
        for name, (dash, desc, codes) in ROLES.items():
            g, created = Group.objects.get_or_create(name=name)
            if created or not g.permissions.exists():
                g.permissions.set([perms[c] for c in codes if c in perms])
            RoleProfile.objects.get_or_create(group=g, defaults={"description": desc, "dashboard": dash, "is_system": True})
        self.stdout.write(f"  roles: {len(ROLES)}")

    def grading(self):
        out = {}
        for key, spec in (("nbte", curricula.NBTE_9_BAND), ("chprbn", curricula.CHPRBN_6_BAND)):
            scheme, created = GradingScheme.objects.get_or_create(
                name=spec["name"], defaults={"source": spec["source"], "pass_mark": spec["pass_mark"]})
            if created:
                for lo, hi, letter, pts, remark in spec["bands"]:
                    GradeBand.objects.create(scheme=scheme, min_score=lo, max_score=hi, letter=letter, points=Decimal(pts), remark=remark)
                for lo, hi, label in spec["classes"]:
                    ClassificationBand.objects.create(scheme=scheme, min_cgpa=Decimal(lo), max_cgpa=Decimal(hi), label=label)
            out[key] = scheme
        return out

    def programmes(self, schemes):
        res_dir = Path(settings.BASE_DIR) / "resources"
        n_courses = 0
        for spec in curricula.PROGRAMMES:
            dname, dcode = spec["department"]
            dept, _ = Department.objects.get_or_create(code=dcode, defaults={"name": f"Department of {dname}"})
            prog, created = Programme.objects.get_or_create(code=spec["code"], defaults={
                "department": dept, "name": spec["name"], "slug": spec["slug"], "award_title": spec["award_title"],
                "regulatory_body": spec["regulatory_body"], "curriculum_reference": spec["curriculum_reference"],
                "duration_years": spec["duration_years"], "level_names": spec["level_names"],
                "grading_scheme": schemes[spec["scheme"]], "ca_max_score": spec["ca"], "exam_max_score": spec["exam"],
                "min_credit_units": 0, "max_credit_units": 40, "min_total_credits": spec["min_total"], "max_total_credits": spec["max_total"],
                "summary": spec["summary"], "goal": spec["goal"], "objectives": spec["objectives"],
                "entry_requirements": spec["entry_requirements"], "structure_notes": spec["structure_notes"],
                "assessment_notes": spec["assessment_notes"], "award_conditions": spec["award_conditions"],
                "icon": spec["icon"], "display_order": spec["order"],
            })
            for (year, term), rows in spec["courses"].items():
                for code, title, lec, tut, prac, ch, cu, ctype in rows:
                    _, made = Course.objects.get_or_create(programme=prog, code=code, year=year, term=term, defaults={
                        "title": title, "credit_units": cu, "lecture_hours": lec, "tutorial_hours": tut, "practical_hours": prac,
                        "contact_hours": ch, "course_type": ctype})
                    n_courses += made
            if created:
                for i, (kind, title, year, term, timing, duration, assessment) in enumerate(spec["practicals"]):
                    code = title.split("(")[-1].rstrip(")") if "(" in title else ""
                    course = Course.objects.filter(programme=prog, code=code).first() if code else None
                    PracticalRequirement.objects.create(programme=prog, kind=kind, title=title, year=year, term=term, timing=timing,
                                                        duration=duration, assessment=assessment, course=course, order=i)
            pdf = res_dir / spec["pdf"]
            if pdf.exists() and not prog.curriculum_file:
                with pdf.open("rb") as fh:
                    prog.curriculum_file.save(f"{prog.code}_curriculum.pdf", File(fh), save=True)
                AcademicDocument.objects.get_or_create(title=f"{prog.name} — official curriculum", programme=prog,
                                                       defaults={"file": prog.curriculum_file.name,
                                                                 "description": spec["curriculum_reference"]})
        self.stdout.write(f"  programmes: {len(curricula.PROGRAMMES)}, new courses: {n_courses}")

    def fees(self):
        cats = {}
        for i, (code, name) in enumerate([("application", "Application form"), ("acceptance", "Acceptance fee"),
                                          ("registration", "Programme registration fee"),
                                          ("departmental", "Departmental and English Class"), ("matriculation", "Matriculation"),
                                          ("examination", "Examination fee")]):
            cats[code], _ = FeeCategory.objects.get_or_create(code=code, defaults={"name": name, "order": i})
        if FeeItem.objects.exists():
            return
        progs = {p.code: p for p in Programme.objects.all()}
        regular = [progs[c] for c in ("PHT", "NUD", "HIM") if c in progs]
        chew = [progs["CHE"]] if "CHE" in progs else []

        def item(cat, name, amount, programmes=(), stage=FeeItem.STUDENT, year=None, instalments=True, first_pct=0):
            fi = FeeItem.objects.create(category=cats[cat], name=name, amount=Decimal(amount), stage=stage, year_of_study=year,
                                        allow_instalments=instalments, min_first_payment_percent=first_pct)
            fi.programmes.set(programmes)

        # Initial reference values supplied by the College (editable in Bursary → Fee schedule).
        item("registration", "Programme registration fee (Public Health, Nutrition & Dietetics, HIM)", 70000, regular)
        item("registration", "Programme registration fee (Community Health Extension Workers)", 120000, chew)
        item("departmental", "Departmental and English Class", 5500)
        item("matriculation", "Matriculation", 3000, year=1)
        item("examination", "Examination fee", 3000)
        item("acceptance", "Acceptance fee (regular programmes)", 10000, regular, stage=FeeItem.ACCEPTANCE, year=1, instalments=False)
        item("acceptance", "Acceptance fee (Community Health)", 20000, chew, stage=FeeItem.ACCEPTANCE, year=1, instalments=False)
        GatewaySettings.load()
        self.stdout.write("  fee schedule: initial reference values loaded")

    def misc(self):
        for i, (name, code, desc, reg, login, enrolled) in enumerate(STATUSES):
            StudentStatus.objects.get_or_create(code=code, defaults={"name": name, "description": desc, "can_register_courses": reg,
                                                                     "can_login": login, "counts_as_enrolled": enrolled, "order": i})
        for i, (name, app_req, stu_req) in enumerate(DOC_TYPES):
            DocumentType.objects.get_or_create(name=name, defaults={"required_for_application": app_req,
                                                                    "required_for_students": stu_req, "order": i})
        for key, name, subject, body, ph in TEMPLATES:
            NotificationTemplate.objects.get_or_create(key=key, defaults={"name": name, "subject": subject, "body": body, "placeholders": ph})

        s = SiteSettings.load()
        if not s.intro:
            s.intro = ("Alfurqan College of Health Sciences and Technology trains health professionals through programmes in Public Health "
                       "Technology, Nutrition and Dietetics, Health Information Management and Community Health, guided by the motto "
                       "“Character and Learning”. [DRAFT — please review]")
            s.vision = "[DRAFT — replace with the College's official vision statement]"
            s.mission = "[DRAFT — replace with the College's official mission statement]"
            s.core_values = ("Character: integrity, discipline and respect in service\nLearning: knowledge and skills for professional practice\n"
                             "[DRAFT — confirm the College's official core values]")
            s.objectives = "[DRAFT — list the College's official institutional objectives, one per line]"
            s.head_message = ("Welcome to Alfurqan College of Health Sciences and Technology. [DRAFT — replace with the official welcome message "
                              "from the Provost/Director and upload a photograph in Institutional settings.]")
            s.admission_overview = ("Admission is open to qualified candidates into the College's programmes. Applications are made online "
                                    "through the Application Portal or in person at the Admissions Office.")
            s.general_requirements = ("Credit passes in five relevant subjects, including English Language and Mathematics, at not more than two sittings "
                                      "(see each programme for the exact subjects)\nEvidence of age (birth certificate or declaration of age)\n"
                                      "Recent passport photograph")
            s.application_steps = ("Create an applicant account on the Application Portal\nComplete your biodata and choose your programme\n"
                                   "Enter your O'Level results\nUpload the required documents\n"
                                   "Pay the application fee online (unless granted a free form)\nSubmit your application and track its status\n"
                                   "If offered admission, accept the offer online and download your admission letter")
            s.save()
        if not HeroSlide.objects.exists():
            HeroSlide.objects.create(title="Training competent health professionals", static_image="img/campus/graduation-1.jpg", order=0)
            HeroSlide.objects.create(title="Celebrating our graduates",
                                     subtitle="Character and learning — preparing practitioners for hospitals and communities.",
                                     static_image="img/campus/graduation-2.jpg", button_text="Meet the College", button_url="/about/", order=1)
        if not Highlight.objects.exists():
            for i, (t, x, ic) in enumerate([
                ("National curricula", "Programmes follow the NBTE and CHPRBN curricula for each diploma.", "bi-journal-check"),
                ("Practical training", "SIWES, supervised clinical and community-based experience built into every programme.", "bi-hospital"),
                ("Character and learning", "Professional ethics and discipline alongside academic excellence.", "bi-award"),
                ("Flexible fee payment", "Pay online and in instalments, with instant digital receipts.", "bi-credit-card-2-front"),
                ("Online and assisted services", "Use the portals yourself, or let our staff help you at the College.", "bi-person-check"),
                ("Career-ready skills", "Graduates are prepared to serve communities, hospitals and health institutions.", "bi-briefcase"),
            ]):
                Highlight.objects.create(title=t, text=x, icon=ic, order=i)
