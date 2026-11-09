import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.academics.models import Programme
from apps.accounts.models import User
from apps.admissions import services
from apps.admissions.models import Application, ApplicationPeriod, OLevelResult
from apps.bursary import services as bursary
from apps.bursary.models import Invoice
from apps.core.tests import factories as f
from apps.students.models import Student


class AdmissionFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        f.load_institution()

    def setUp(self):
        self.sess, _ = f.session_and_semester()
        today = timezone.localdate()
        self.period = ApplicationPeriod.objects.create(name="Test exercise", session=self.sess, opens_on=today - datetime.timedelta(days=1),
                                                       closes_on=today + datetime.timedelta(days=30), application_fee=Decimal("5000"))
        self.period.programmes.set(Programme.objects.all())
        self.officer = f.staff("adm", "Admission Officer")
        self.user = User.objects.create_user("app@t.invalid", "app@t.invalid", "Passw0rd!x", user_type="applicant")
        self.app = Application.objects.create(user=self.user, period=self.period, first_choice=Programme.objects.get(code="CHE"),
                                              first_name="Zainab", last_name="Musa", gender="F", date_of_birth=datetime.date(2005, 1, 1),
                                              phone="08030000000", address="Somewhere", state_of_origin="Gombe")
        for subj in ("English Language", "Mathematics", "Biology", "Chemistry", "Physics"):
            OLevelResult.objects.create(application=self.app, exam_type="WAEC", exam_year=2023, subject=subj, grade="B3")

    def _pay_fee(self):
        inv = bursary.ensure_application_invoice(self.app, self.user)
        bursary.record_offline_payment(inv, inv.balance, "bank_deposit", "APP-1", self.officer, verify=True)

    def test_cannot_submit_without_required_items(self):
        with self.assertRaises(ValidationError) as ctx:
            services.submit(self.app, self.user)
        self.assertIn("Application fee payment", " ".join(ctx.exception.messages))

    def test_fee_exemption_allows_free_form(self):
        services.grant_fee_exemption(self.app, self.officer, "Scholarship nominee")
        self.app.refresh_from_db()
        self.assertTrue(self.app.fee_settled)

    def test_staff_can_force_submit_and_it_is_recorded(self):
        services.submit(self.app, self.officer, force=True)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, Application.SUBMITTED)
        self.assertTrue(self.app.application_number.startswith("AFC/APP/2026/"))
        ev = self.app.events.get(action="Submitted")
        self.assertTrue(ev.via_staff)
        self.assertIn("overridden", ev.note)

    def test_admit_accept_converts_once_with_invoices(self):
        services.grant_fee_exemption(self.app, self.officer, "Free form")
        self.app.documents.model  # documents not required in this test setup
        from apps.students.models import DocumentType
        DocumentType.objects.update(required_for_application=False)
        services.submit(self.app, self.user)
        services.decide(self.app, "admit", self.officer)
        student = services.respond_to_offer(self.app, True, self.user)
        self.assertEqual(student.programme.code, "CHE")
        self.assertTrue(student.matric_number.startswith("AFC/CHE/26/"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.user_type, "student")
        self.assertEqual(Student.objects.filter(application=self.app).count(), 1)
        with self.assertRaises(ValidationError):
            services.respond_to_offer(self.app, True, self.user)
        purposes = set(Invoice.objects.filter(student=student).values_list("purpose", flat=True))
        self.assertEqual(purposes, {"acceptance", "fees"})
        self.assertEqual(Invoice.objects.get(student=student, purpose="acceptance").gross_amount, Decimal("20000.00"))
        # application history preserved
        self.assertTrue(self.app.events.filter(action="Admission offer accepted").exists())

    def test_matric_numbers_are_unique_and_sequential(self):
        a = f.student("PHT")
        b = f.student("PHT")
        self.assertNotEqual(a.matric_number, b.matric_number)
        self.assertTrue(b.matric_number.endswith("0002"))
