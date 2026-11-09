import datetime

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.core.models import AuditLog
from apps.core.tests import factories as f
from apps.registration import services as reg
from apps.registration.models import CourseRegistration, RegistrationEvent
from apps.students.models import StudentStatus


class RegistrationRuleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        f.load_institution()

    def setUp(self):
        _, self.sem = f.session_and_semester()
        self.officer = f.staff("acad", "Academic Officer")  # has override permission
        self.hod = f.staff("hod", "Head of Department")      # can register on behalf, no override
        self.s = f.student("NUD", actor=self.officer)
        self.y1s1 = f.courses("NUD", 1, 1)

    def test_student_self_registration_and_submit(self):
        r = reg.add_courses(self.s, self.sem, self.y1s1, self.s.user)
        self.assertEqual(r.total_units, 23)
        r = reg.submit_registration(r, self.s.user)
        self.assertEqual(r.status, CourseRegistration.SUBMITTED)  # approval required by default
        self.assertFalse(RegistrationEvent.objects.filter(registration=r, via_staff=True).exists())

    def test_duplicate_registration_prevented(self):
        reg.add_courses(self.s, self.sem, self.y1s1[:2], self.s.user)
        with self.assertRaises(ValidationError):
            reg.add_courses(self.s, self.sem, self.y1s1[:1], self.s.user)

    def test_wrong_term_and_programme_rejected(self):
        with self.assertRaises(ValidationError):
            reg.add_courses(self.s, self.sem, f.courses("NUD", 1, 2)[:1], self.s.user)
        with self.assertRaises(ValidationError):
            reg.add_courses(self.s, self.sem, f.courses("PHT", 1, 1)[:1], self.s.user)

    def test_credit_ceiling_and_override(self):
        prog = self.s.programme
        prog.max_credit_units = 10
        prog.save()
        with self.assertRaises(ValidationError):
            reg.add_courses(self.s, self.sem, self.y1s1, self.s.user)
        r = reg.add_courses(self.s, self.sem, self.y1s1, self.officer)  # override permission
        self.assertEqual(r.total_units, 23)

    def test_prerequisite_enforced(self):
        a, b = self.y1s1[0], self.y1s1[1]
        b.prerequisites.add(a)
        with self.assertRaises(ValidationError):
            reg.add_courses(self.s, self.sem, [b], self.s.user)

    def test_deadline_blocks_student_but_not_officer(self):
        self.sem.registration_closes = timezone.localdate() - datetime.timedelta(days=1)
        self.sem.save()
        with self.assertRaises(ValidationError):
            reg.add_courses(self.s, self.sem, self.y1s1[:1], self.s.user)
        with self.assertRaises(ValidationError):
            reg.add_courses(self.s, self.sem, self.y1s1[:1], self.hod)
        r = reg.add_courses(self.s, self.sem, self.y1s1[:1], self.officer)
        self.assertEqual(r.items.count(), 1)

    def test_staff_assisted_registration_is_recorded_as_on_behalf(self):
        r = reg.add_courses(self.s, self.sem, self.y1s1[:3], self.hod)
        self.assertTrue(all(i.via_staff for i in r.items.all()))
        self.assertTrue(RegistrationEvent.objects.filter(registration=r, via_staff=True, action="added").exists())
        log = AuditLog.objects.filter(action="courses_added").latest("timestamp")
        self.assertEqual(log.on_behalf_of, self.s.user)

    def test_staff_with_approval_permission_auto_approves(self):
        r = reg.add_courses(self.s, self.sem, self.y1s1, self.hod)
        r = reg.submit_registration(r, self.hod)
        self.assertEqual(r.status, CourseRegistration.APPROVED)

    def test_suspended_student_cannot_register(self):
        self.s.status = StudentStatus.get("suspended")
        self.s.save()
        with self.assertRaises(ValidationError):
            reg.add_courses(self.s, self.sem, self.y1s1[:1], self.s.user)

    def test_submitted_registration_locked_for_student(self):
        r = reg.add_courses(self.s, self.sem, self.y1s1, self.s.user)
        reg.submit_registration(r, self.s.user)
        with self.assertRaises(ValidationError):
            reg.drop_course(r, self.y1s1[0], self.s.user)
        reg.review_registration(r, False, self.officer, "Remove one course")
        r.refresh_from_db()
        reg.drop_course(r, self.y1s1[0], self.s.user)
        self.assertEqual(r.items.count(), len(self.y1s1) - 1)

    def test_first_registration_activates_admitted_student(self):
        self.s.status = StudentStatus.get("admitted")
        self.s.save()
        r = reg.add_courses(self.s, self.sem, self.y1s1, self.s.user)
        reg.submit_registration(r, self.s.user)
        self.s.refresh_from_db()
        self.assertEqual(self.s.status.code, "active")
