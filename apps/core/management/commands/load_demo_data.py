"""Populate the system with clearly-marked SAMPLE data for demonstration.

    python manage.py load_demo_data          # create sample data
    python manage.py load_demo_data --purge  # remove all sample data

Every record created here is flagged `is_sample=True` (directly or through its
student/applicant/user) and is shown with a "Sample" tag in the interface.
All sample accounts use the password printed at the end.
"""
import datetime
import random
from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.academics.models import AcademicSession, Course, CourseAllocation, Department, Programme, Semester
from apps.accounts.models import StaffProfile, User
from apps.admissions import services as adm
from apps.admissions.models import Application, ApplicationPeriod, OLevelResult
from apps.bursary import services as bursary
from apps.bursary.models import Invoice, Payment, TransactionLog
from apps.registration import services as reg_services
from apps.registration.models import CourseRegistration
from apps.results import services as res
from apps.results.models import ResultSheet
from apps.students import services as stu
from apps.students.models import Student, StudentStatus
from apps.website.models import Post

PASSWORD = "Sample@2026"
FIRST_M = ["Abubakar", "Musa", "Ibrahim", "Usman", "Aliyu", "Sani", "Yusuf", "Bello", "Haruna", "Idris", "Ahmed", "Suleiman",
           "Emmanuel", "Daniel", "Samuel", "Chinedu", "Tunde", "Kabiru", "Nasiru", "Umar"]
FIRST_F = ["Aisha", "Fatima", "Zainab", "Hauwa", "Maryam", "Hadiza", "Amina", "Khadija", "Rukayya", "Halima", "Safiya",
           "Blessing", "Grace", "Esther", "Ngozi", "Funmilayo", "Asmau", "Jamila", "Saadatu", "Bilkisu"]
LAST = ["Abdullahi", "Mohammed", "Bello", "Usman", "Lawal", "Garba", "Danjuma", "Adamu", "Shehu", "Mustapha", "Ismail",
        "Okafor", "Adeyemi", "Yakubu", "Sulaiman", "Tukur", "Bappah", "Gambo", "Jibrin", "Aminu"]
STATES = ["Gombe", "Bauchi", "Adamawa", "Borno", "Yobe", "Taraba", "Kano", "Plateau"]
SUBJECTS = ["English Language", "Mathematics", "Biology", "Chemistry", "Physics", "Agricultural Science", "Economics"]


class Command(BaseCommand):
    help = "Create (or --purge) clearly-marked sample data for demonstration."

    def add_arguments(self, parser):
        parser.add_argument("--purge", action="store_true", help="Delete all sample data")

    def handle(self, *args, **opts):
        if opts["purge"]:
            self.purge()
            return
        if not Programme.objects.exists():
            raise CommandError("Run `python manage.py setup_institution` first.")
        if User.objects.filter(is_sample=True).exists():
            raise CommandError("Sample data already exists. Run with --purge first to recreate it.")
        random.seed(2026)
        with transaction.atomic():
            self.create()
        self.stdout.write(self.style.SUCCESS("Sample data created."))
        self.stdout.write(f"All sample accounts use the password: {PASSWORD}")
        self.stdout.write("Staff:    sample.superadmin, sample.admin, sample.academic, sample.admission, sample.bursary, sample.hod.pht, sample.hod.che, sample.lecturer1..4")
        self.stdout.write(f"Student:  {self.example_student}")
        self.stdout.write(f"Applicant: {self.example_applicant}")

    # ------------------------------------------------------------------
    def _name(self, gender):
        return random.choice(FIRST_M if gender == "M" else FIRST_F), random.choice(LAST)

    def _staff(self, username, first, last, role, dept=None, designation=""):
        u = User(username=username, first_name=first, last_name=last, email=f"{username}@sample.invalid", user_type="staff",
                 is_sample=True)
        u.set_password(PASSWORD)
        u.save()
        u.groups.add(Group.objects.get(name=role))
        StaffProfile.objects.create(user=u, staff_id=f"SMP/{username.split('.')[-1].upper()}", department=dept, designation=designation)
        return u

    def create(self):
        today = timezone.localdate()
        s_prev, _ = AcademicSession.objects.get_or_create(name="2025/2026", defaults={"start_date": datetime.date(2025, 10, 6), "end_date": datetime.date(2026, 9, 25)})
        s_cur, _ = AcademicSession.objects.get_or_create(name="2026/2027", defaults={"start_date": datetime.date(2026, 10, 5), "end_date": datetime.date(2027, 9, 24)})
        s_cur.is_current = True
        s_cur.save()
        prev1, _ = Semester.objects.get_or_create(session=s_prev, term=1, defaults={"start_date": datetime.date(2025, 10, 6), "end_date": datetime.date(2026, 2, 13)})
        prev2, _ = Semester.objects.get_or_create(session=s_prev, term=2, defaults={"start_date": datetime.date(2026, 3, 2), "end_date": datetime.date(2026, 7, 10)})
        cur1, _ = Semester.objects.get_or_create(session=s_cur, term=1, defaults={
            "start_date": datetime.date(2026, 10, 5), "end_date": datetime.date(2027, 2, 12),
            "registration_opens": datetime.date(2026, 10, 5), "registration_closes": today + datetime.timedelta(days=35),
            "add_drop_closes": today + datetime.timedelta(days=49)})
        cur1.is_current = True
        cur1.save()

        admin = self._staff("sample.admin", "Sample", "Administrator", "Administrator", designation="Administrator")
        superadmin = self._staff("sample.superadmin", "Sample", "Super Admin", "Super Administrator", designation="Registrar (sample)")
        actor = superadmin
        self._staff("sample.academic", "Halima", "Garba", "Academic Officer", designation="Academic Officer")
        self._staff("sample.admission", "Kabiru", "Lawal", "Admission Officer", designation="Admission Officer")
        self._staff("sample.bursary", "Ngozi", "Okafor", "Bursary Officer", designation="Bursar")
        depts = {d.code: d for d in Department.objects.all()}
        hod_pht = self._staff("sample.hod.pht", "Yusuf", "Danjuma", "Head of Department", depts.get("PHT"), "HOD, Public Health")
        hod_che = self._staff("sample.hod.che", "Hauwa", "Shehu", "Head of Department", depts.get("CHE"), "HOD, Community Health")
        for u in (hod_pht, hod_che):
            u.groups.add(Group.objects.get(name="Lecturer"))
        if depts.get("PHT") and not depts["PHT"].hod:
            depts["PHT"].hod = hod_pht
            depts["PHT"].save()
        if depts.get("CHE") and not depts["CHE"].hod:
            depts["CHE"].hod = hod_che
            depts["CHE"].save()
        lecturers = [self._staff(f"sample.lecturer{i}", *self._name(random.choice("MF")), "Lecturer",
                                 random.choice(list(depts.values())), "Lecturer II") for i in range(1, 5)] + [hod_pht, hod_che]

        active = StudentStatus.get("active")
        programmes = list(Programme.objects.all())
        all_students = []
        for prog in programmes:
            for entry, year, count in ((s_prev, 2, 6), (s_cur, 1, 5)):
                for _ in range(count):
                    g = random.choice("MF")
                    first, last = self._name(g)
                    data = {"first_name": first, "last_name": last, "middle_name": random.choice(["", "A.", "M.", "I."]), "gender": g,
                            "date_of_birth": datetime.date(random.randint(1998, 2007), random.randint(1, 12), random.randint(1, 28)),
                            "phone": f"080{random.randint(10000000, 99999999)}", "email": "", "address": f"{random.randint(1, 120)} Sample Street",
                            "state_of_origin": random.choice(STATES), "lga": "", "nationality": "Nigerian",
                            "next_of_kin_name": f"{random.choice(FIRST_M)} {last}", "next_of_kin_relationship": "Parent",
                            "next_of_kin_phone": f"070{random.randint(10000000, 99999999)}"}
                    s, _ = stu.create_student(data, actor, programme=prog, session=entry, current_year=1, status=active,
                                              password=PASSWORD, is_sample=True)
                    s.user.must_change_password = False
                    s.user.save(update_fields=["must_change_password"])
                    if year == 2:
                        all_students.append((s, "returning"))
                    else:
                        all_students.append((s, "new"))
        self.example_student = Student.objects.filter(is_sample=True).first().matric_number

        # Past session: register, score, publish (returning students)
        for sem in (prev1, prev2):
            for s, kind in all_students:
                if kind != "returning":
                    continue
                courses = list(Course.objects.filter(programme=s.programme, year=1, term=sem.term))
                self._register(s, sem, courses, actor, approve=True)
            self._results(sem, actor, lecturers, publish=True)
        # promote returning students to Year 2
        for s, kind in all_students:
            if kind == "returning":
                stu.promote(s, actor, s_cur)
                s.refresh_from_db()

        # Current semester
        for i, (s, kind) in enumerate(all_students):
            s.refresh_from_db()
            courses = list(Course.objects.filter(programme=s.programme, year=s.current_year, term=1))
            if kind == "returning":
                self._register(s, cur1, courses, actor, approve=i % 3 != 0)
            elif i % 2 == 0:
                self._register(s, cur1, courses[: max(1, len(courses) - 2)], s.user, approve=False, submit=False)
        for c in Course.objects.filter(term=1, year__in=[1, 2], is_active=True):
            lec = random.choice([l for l in lecturers if l.staff_profile.department_id == c.programme.department_id] or lecturers)
            CourseAllocation.objects.get_or_create(course=c, semester=cur1, lecturer=lec, defaults={"allocated_by": actor})
        # current semester result sheets at different workflow stages
        sheets = []
        for c in Course.objects.filter(term=1, year=2, is_active=True)[:12]:
            if reg_services.registered_items(c, cur1).exists():
                sheets.append(res.get_or_create_sheet(c, cur1, actor))
        for i, sh in enumerate(sheets):
            self._fill(sh, actor)
            alloc = CourseAllocation.objects.filter(course=sh.course, semester=cur1).first()
            if i % 4 in (1, 2, 3):
                res.submit_sheet(sh, alloc.lecturer if alloc else actor)
            if i % 4 in (2, 3):
                res.hod_review(sh, True, superadmin, "Reviewed")
            if i % 4 == 3:
                res.final_approval(sh, True, superadmin, "")

        # Invoices & payments
        for s, kind in all_students:
            for sess in ([s_prev, s_cur] if kind == "returning" else [s_cur]):
                inv = bursary.generate_student_invoice(s, sess, actor, year=1 if sess == s_prev or kind == "new" else 2)
                if inv is None:
                    continue
                r = random.random()
                if sess == s_prev or r < 0.35:
                    self._pay(inv, inv.balance, actor)
                elif r < 0.75:
                    self._pay(inv, (inv.balance * Decimal("0.5")).quantize(Decimal("1")), actor)
        some = Invoice.objects.filter(is_sample=True, status=Invoice.UNPAID).first()
        if some:
            bursary.record_offline_payment(some, 20000, "bank_deposit", f"SMP-TELLER-{some.pk}", actor, is_sample=True)
        inv = Invoice.objects.filter(is_sample=True, status=Invoice.PART_PAID).first()
        if inv:
            bursary.add_adjustment(inv, "scholarship", min(Decimal("10000"), inv.balance), "Sample scholarship", actor, "Sample Foundation")

        # Applications
        period, _ = ApplicationPeriod.objects.get_or_create(name="2026/2027 Admission Exercise (sample)", defaults={
            "session": s_cur, "opens_on": today - datetime.timedelta(days=60), "closes_on": today + datetime.timedelta(days=45),
            "application_fee": Decimal("5000"), "instructions": "Complete every section and upload clear documents."})
        period.programmes.set(programmes)
        outcomes = ["draft", "submitted", "submitted", "review", "admit", "admit", "admit_accept", "reject", "submitted", "admit", "exempt"]
        for i, outcome in enumerate(outcomes):
            g = random.choice("MF")
            first, last = self._name(g)
            email = f"applicant{i + 1}@sample.invalid"
            u = User(username=email, email=email, first_name=first, last_name=last, user_type="applicant", is_sample=True)
            u.set_password(PASSWORD)
            u.save()
            prog = random.choice(programmes)
            app = Application.objects.create(user=u, period=period, first_choice=prog, first_name=first, last_name=last, gender=g,
                                             date_of_birth=datetime.date(random.randint(2002, 2008), random.randint(1, 12), 15),
                                             phone=f"081{random.randint(10000000, 99999999)}", email=email, address="Sample address",
                                             state_of_origin=random.choice(STATES), created_by=u, is_sample=True,
                                             previous_institution="Government Secondary School (sample)")
            adm.record_event(app, "Application started", u)
            if i == 0:
                self.example_applicant = email
            if outcome == "draft":
                continue
            for subj in SUBJECTS[:6]:
                OLevelResult.objects.create(application=app, exam_type="WAEC", exam_year=2024, exam_number=f"42{random.randint(100000, 999999)}",
                                            subject=subj, grade=random.choice(["A1", "B2", "B3", "C4", "C5", "C6"]))
            if outcome == "exempt":
                adm.grant_fee_exemption(app, admin, "Sample: community scholarship nominee")
            else:
                inv = bursary.ensure_application_invoice(app, u)
                self._pay(inv, inv.balance, u, online=True)
            adm.submit(app, u, force=True)
            if outcome in ("review",):
                adm.decide(app, "review", admin)
            elif outcome.startswith("admit"):
                adm.decide(app, "admit", admin, note="Sample admission")
                if outcome == "admit_accept":
                    adm.respond_to_offer(app, True, u)
            elif outcome == "reject":
                adm.decide(app, "reject", admin, note="Did not meet O'Level requirements (sample)")

        for title, cat, body, pinned in [
            ("Sample: 2026/2027 admission exercise is open", Post.ADMISSION,
             "This is a sample announcement. Applications are open through the Application Portal.", True),
            ("Sample: Course registration for the first semester", Post.ANNOUNCEMENT,
             "This is a sample notice. Students should complete course registration before the deadline shown in the portal.", False),
            ("Sample: Graduation ceremony held", Post.NEWS,
             "This is a sample news item demonstrating the news section. Replace it with real College news.", False),
        ]:
            Post.objects.create(title=title, category=cat, body=body, summary=body[:140], is_pinned=pinned, author=admin, is_sample=True)

    # ------------------------------------------------------------------
    def _register(self, s, sem, courses, actor, approve=True, submit=True):
        if not courses:
            return
        reg = CourseRegistration.objects.create(student=s, semester=sem, year_of_study=s.current_year, created_by=actor)
        for c in courses:
            reg.items.create(course=c, added_by=actor)
        if submit:
            reg.status = CourseRegistration.APPROVED if approve else CourseRegistration.SUBMITTED
            reg.submitted_at = timezone.now()
            if approve:
                reg.reviewed_by, reg.reviewed_at = actor, timezone.now()
            reg.save()

    def _fill(self, sheet, actor):
        entries = {}
        for sc in sheet.scores.all():
            ca = Decimal(random.randint(int(sheet.ca_max * Decimal("0.4")), int(sheet.ca_max)))
            ex = Decimal(random.randint(int(sheet.exam_max * Decimal("0.25")), int(sheet.exam_max * Decimal("0.95"))))
            entries[sc.student_id] = (ca, ex)
        res.save_scores(sheet, entries, actor)

    def _results(self, sem, actor, lecturers, publish):
        courses = Course.objects.filter(registrations__registration__semester=sem).distinct()
        for c in courses:
            sh = res.get_or_create_sheet(c, sem, actor)
            lec = random.choice(lecturers)
            CourseAllocation.objects.get_or_create(course=c, semester=sem, lecturer=lec, defaults={"allocated_by": actor})
            self._fill(sh, actor)
            res.submit_sheet(sh, actor)
            res.hod_review(sh, True, actor, "")
            res.final_approval(sh, True, actor, "")
            if publish:
                res.publish(sh, actor)

    def _pay(self, inv, amount, actor, online=False):
        if amount <= 0:
            return
        if online:
            p = Payment.objects.create(invoice=inv, amount=amount, method="online", gateway="sandbox", reference=bursary.new_reference("SMP"),
                                       initiated_by=actor, is_sample=True)
            TransactionLog.objects.create(payment=p, reference=p.reference, gateway="sandbox", event="sandbox_outcome", success=True)
            bursary._mark_successful(p, gateway_data={"sandbox": True})
        else:
            bursary.record_offline_payment(inv, amount, random.choice(["bank_deposit", "bank_transfer", "pos"]),
                                           bursary.new_reference("SMP"), actor, verify=True, is_sample=True)

    # ------------------------------------------------------------------
    @transaction.atomic
    def purge(self):
        from apps.notifications.models import Notification

        students = Student.objects.filter(is_sample=True)
        apps = Application.objects.filter(is_sample=True)
        invoices = Invoice.objects.filter(is_sample=True)
        for p in Payment.objects.filter(invoice__in=invoices):
            p.refunds.all().delete()
            p.logs.all().delete()
        Payment.objects.filter(invoice__in=invoices).delete()
        for inv in invoices:
            inv.adjustments.all().delete()
        invoices.delete()
        from apps.results.models import Score
        Score.objects.filter(student__in=students).delete()
        ResultSheet.objects.filter(scores__isnull=True).delete()
        CourseRegistration.objects.filter(student__in=students).delete()
        sample_users = User.objects.filter(is_sample=True)
        CourseAllocation.objects.filter(lecturer__in=sample_users).delete()
        Department.objects.filter(hod__in=sample_users).update(hod=None)
        Student.objects.filter(pk__in=students).update(application=None)
        n_students = students.count()
        students.delete()
        apps.delete()
        Notification.objects.filter(recipient__in=sample_users).delete()
        Post.objects.filter(is_sample=True).delete()
        ApplicationPeriod.objects.filter(name__endswith="(sample)", applications__isnull=True).delete()
        n_users = sample_users.count()
        from apps.core.models import ImportBatch
        ImportBatch.objects.filter(created_by__in=sample_users).delete()
        sample_users.delete()
        self.stdout.write(self.style.SUCCESS(f"Removed sample data: {n_students} students, {n_users} accounts."))
