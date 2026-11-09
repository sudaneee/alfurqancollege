from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from apps.academics.models import Programme
from apps.core.models import AuditLog
from apps.core.tests import factories as f
from apps.registration import services as reg
from apps.results import services as res
from apps.results.models import ResultSheet, Score


class GradingEngineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        f.load_institution()

    def test_nbte_scale_matches_curriculum(self):
        scheme = Programme.objects.get(code="NUD").grading_scheme
        cases = {100: ("A", "4.00"), 75: ("A", "4.00"), 74: ("AB", "3.50"), 70: ("AB", "3.50"), 64: ("BC", "3.00"),
                 50: ("CD", "2.50"), 40: ("E", "2.00"), 39: ("F", "0.00"), 0: ("F", "0.00")}
        for score, (letter, pts) in cases.items():
            band = scheme.band_for(score)
            self.assertEqual((band.letter, str(band.points)), (letter, pts), score)

    def test_decimal_total_between_bands_falls_to_lower_band(self):
        scheme = Programme.objects.get(code="NUD").grading_scheme
        self.assertEqual(scheme.band_for(Decimal("74.5")).letter, "AB")

    def test_chew_scale_pass_mark_50(self):
        scheme = Programme.objects.get(code="CHE").grading_scheme
        self.assertEqual(scheme.pass_mark, 50)
        self.assertEqual(scheme.band_for(70).letter, "A")
        self.assertEqual(scheme.band_for(49).letter, "F")
        self.assertEqual(scheme.band_for(50).remark, "Pass")

    def test_classification(self):
        scheme = Programme.objects.get(code="PHT").grading_scheme
        self.assertEqual(scheme.classify(Decimal("3.50")), "Distinction")
        self.assertEqual(scheme.classify(Decimal("3.49")), "Upper Credit")
        self.assertEqual(scheme.classify(Decimal("2.99")), "Lower Credit")
        self.assertEqual(scheme.classify(Decimal("2.00")), "Pass")
        self.assertEqual(scheme.classify(Decimal("1.99")), "Fail")


class ResultWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        f.load_institution()

    def setUp(self):
        _, self.sem = f.session_and_semester()
        self.admin = f.staff("super", "Super Administrator")
        self.lecturer = f.staff("lect", "Lecturer")
        self.other = f.staff("lect2", "Lecturer")
        self.hod = f.staff("hod", "Head of Department")
        self.officer = f.staff("acad", "Academic Officer")
        prog = Programme.objects.get(code="PHT")
        prog.department.hod = self.hod
        prog.department.save()
        self.course = f.courses("PHT", 1, 1)[0]  # PHT 111, 3 units
        f.allocate(self.course, self.sem, self.lecturer)
        self.s1 = f.student("PHT", actor=self.admin, first_name="Amina")
        self.s2 = f.student("PHT", actor=self.admin, first_name="Bello")
        for s in (self.s1, self.s2):
            r = reg.add_courses(s, self.sem, [self.course], s.user)
            reg.submit_registration(r, s.user)
        self.sheet = res.get_or_create_sheet(self.course, self.sem, self.lecturer)

    def test_registered_students_are_on_sheet_without_duplicates(self):
        self.assertEqual(self.sheet.scores.count(), 2)
        res.sync_sheet_students(self.sheet)
        self.assertEqual(self.sheet.scores.count(), 2)

    def test_totals_and_grades_computed(self):
        res.save_scores(self.sheet, {self.s1.pk: (Decimal(25), Decimal(55)), self.s2.pk: (Decimal(10), Decimal(25))}, self.lecturer)
        a = Score.objects.get(sheet=self.sheet, student=self.s1)
        b = Score.objects.get(sheet=self.sheet, student=self.s2)
        self.assertEqual((a.total, a.grade, a.points), (Decimal(80), "A", Decimal("4.00")))
        self.assertEqual((b.total, b.grade), (Decimal(35), "F"))
        self.assertFalse(b.passed)

    def test_score_limits_validated(self):
        with self.assertRaises(ValidationError):
            res.parse_score("31", self.sheet.ca_max, "CA")
        with self.assertRaises(ValidationError):
            res.parse_score("-1", self.sheet.exam_max, "Exam")
        with self.assertRaises(ValidationError):
            res.parse_score("abc", self.sheet.exam_max, "Exam")

    def test_unallocated_lecturer_cannot_enter_scores(self):
        with self.assertRaises(PermissionDenied):
            res.save_scores(self.sheet, {self.s1.pk: (Decimal(1), Decimal(1))}, self.other)

    def test_full_workflow_and_student_visibility(self):
        res.save_scores(self.sheet, {self.s1.pk: (Decimal(20), Decimal(50)), self.s2.pk: (Decimal(15), Decimal(40))}, self.lecturer)
        res.submit_sheet(self.sheet, self.lecturer)
        self.assertEqual(list(res.published_scores(self.s1)), [])
        with self.assertRaises(PermissionDenied):
            res.hod_review(self.sheet, True, self.other, "")
        res.hod_review(self.sheet, True, self.hod, "ok")
        res.final_approval(self.sheet, True, self.officer, "")
        res.publish(self.sheet, self.officer)
        self.sheet.refresh_from_db()
        self.assertEqual(self.sheet.status, ResultSheet.PUBLISHED)
        self.assertEqual(len(res.published_scores(self.s1)), 1)
        self.assertEqual(res.cgpa_for(self.s1), Decimal("3.50"))  # 70 -> AB (3.50)

    def test_incomplete_sheet_cannot_be_submitted(self):
        res.save_scores(self.sheet, {self.s1.pk: (Decimal(20), None)}, self.lecturer)
        with self.assertRaises(ValidationError):
            res.submit_sheet(self.sheet, self.lecturer)

    def test_locked_result_needs_override_and_reason_and_is_audited(self):
        res.save_scores(self.sheet, {self.s1.pk: (Decimal(20), Decimal(50)), self.s2.pk: (Decimal(15), Decimal(40))}, self.lecturer)
        res.submit_sheet(self.sheet, self.lecturer)
        with self.assertRaises(PermissionDenied):
            res.save_scores(self.sheet, {self.s1.pk: (Decimal(30), Decimal(50))}, self.lecturer)
        with self.assertRaises(ValidationError):
            res.save_scores(self.sheet, {self.s1.pk: (Decimal(30), Decimal(50))}, self.admin, reason="")
        res.save_scores(self.sheet, {self.s1.pk: (Decimal(30), Decimal(50))}, self.admin, reason="Marking error")
        log = AuditLog.objects.filter(action="score_changed", note="Marking error").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.changes["ca"], ["20.00", "30"])

    def test_return_requires_reason_and_reopen(self):
        res.save_scores(self.sheet, {self.s1.pk: (Decimal(20), Decimal(50)), self.s2.pk: (Decimal(15), Decimal(40))}, self.lecturer)
        res.submit_sheet(self.sheet, self.lecturer)
        with self.assertRaises(ValidationError):
            res.hod_review(self.sheet, False, self.hod, "")
        res.hod_review(self.sheet, False, self.hod, "Check CA for 2 students")
        self.sheet.refresh_from_db()
        self.assertTrue(self.sheet.is_editable)
        res.submit_sheet(self.sheet, self.lecturer)
        res.hod_review(self.sheet, True, self.hod)
        res.final_approval(self.sheet, True, self.officer)
        res.publish(self.sheet, self.officer)
        with self.assertRaises(PermissionDenied):
            res.reopen(self.sheet, self.officer, "x")
        res.reopen(self.sheet, self.admin, "Board directive")
        self.sheet.refresh_from_db()
        self.assertEqual(self.sheet.status, ResultSheet.DRAFT)
        self.assertEqual(res.published_scores(self.s1).count(), 0)


class GPATests(TestCase):
    @classmethod
    def setUpTestData(cls):
        f.load_institution()

    def test_weighted_gpa_and_pass_fail_exclusion(self):
        admin = f.staff("super", "Super Administrator")
        _, sem = f.session_and_semester(term=2)
        s = f.student("HIM", actor=admin)
        cs = f.courses("HIM", 1, 2)
        siwes = next(c for c in cs if c.code == "HIM 122")
        siwes.pass_fail_only = True
        siwes.save()
        a = next(c for c in cs if c.credit_units == 3 and c.code != "HIM 122")  # 3 units
        b = next(c for c in cs if c.credit_units == 2)  # 2 units
        r = reg.add_courses(s, sem, [a, b, siwes], admin)
        reg.submit_registration(r, admin)
        for course, (ca, ex) in ((a, (30, 50)), (b, (20, 30)), (siwes, (10, 20))):
            sh = res.get_or_create_sheet(course, sem, admin)
            res.save_scores(sh, {s.pk: (Decimal(ca), Decimal(ex))}, admin)
            res.submit_sheet(sh, admin)
            res.hod_review(sh, True, admin)
            res.final_approval(sh, True, admin)
            res.publish(sh, admin)
        # a: 80 -> A 4.00 x3 = 12 ; b: 50 -> CD 2.50 x2 = 5 ; SIWES excluded -> 17/5 = 3.40
        rec = res.academic_record(s)
        self.assertEqual(rec["cgpa"], Decimal("3.40"))
        self.assertEqual(rec["classification"], "Upper Credit")
        self.assertEqual(rec["semesters"][0]["units"], 5)
