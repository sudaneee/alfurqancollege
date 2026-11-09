import io
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.core.excel import build_workbook
from apps.core.models import AuditLog, ImportBatch
from apps.core.tests import factories as f
from apps.registration import services as reg
from apps.results import services as res
from apps.results.models import Score
from apps.students.models import Student


def xlsx(headers, rows, name="upload.xlsx"):
    buf = io.BytesIO()
    build_workbook(headers, rows).save(buf)
    return SimpleUploadedFile(name, buf.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@override_settings(ALLOWED_HOSTS=["testserver"])
class BulkImportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        f.load_institution()

    def setUp(self):
        self.sess, self.sem = f.session_and_semester()
        self.officer = f.staff("acad", "Academic Officer")
        self.client.force_login(self.officer)

    def test_student_import_preview_then_confirm(self):
        existing = f.student("PHT", actor=self.officer)
        headers = ["Matric Number", "Programme Code", "Session of Admission", "Current Year", "Status Code", "First Name", "Middle Name",
                   "Surname", "Gender", "Date of Birth", "Phone", "Email"]
        rows = [["", "PHT", "2026/2027", 1, "active", "Musa", "", "Ali", "Male", "2004-02-01", "08011111111", ""],
                ["", "NUD", "2026/2027", 1, "", "Rukayya", "", "Bello", "F", "2005-03-02", "", "ruk@t.invalid"],
                [existing.matric_number, "PHT", "2026/2027", 1, "", "Dup", "", "Licate", "M", "", "", ""],
                ["", "XXX", "2026/2027", 1, "", "Bad", "", "Programme", "M", "", "", ""],
                ["", "PHT", "2026/2027", 1, "", "Bad", "", "Date", "M", "31/31/2020", "", ""]]
        r = self.client.post("/staff/bulk/students_create/", {"file": xlsx(headers, rows)})
        batch = ImportBatch.objects.get()
        self.assertRedirects(r, f"/staff/bulk/batch/{batch.pk}/")
        self.assertEqual(batch.valid_count, 2)
        self.assertEqual(batch.error_count, 3)
        self.assertEqual(Student.objects.count(), 1)  # nothing saved before confirmation
        self.client.post(f"/staff/bulk/batch/{batch.pk}/confirm/")
        batch.refresh_from_db()
        self.assertEqual(batch.summary, {"total": 5, "applied": 2, "failed": 3, "skipped": 0})
        self.assertEqual(Student.objects.count(), 3)
        failed = self.client.get(f"/staff/bulk/batch/{batch.pk}/failed.xlsx")
        self.assertEqual(failed.status_code, 200)
        self.assertTrue(AuditLog.objects.filter(action="bulk_students_create").exists())

    def test_bulk_update_never_overwrites_with_blanks(self):
        s = f.student("PHT", actor=self.officer)
        s.phone = "08099999999"
        s.save()
        headers = ["Matric Number", "Phone", "Address"]
        r = self.client.post("/staff/bulk/students_update/", {"file": xlsx(headers, [[s.matric_number, "", "New address"]])})
        batch = ImportBatch.objects.get()
        self.assertIn("address", batch.rows[0]["changes"])
        self.assertNotIn("phone", batch.rows[0]["changes"])
        self.client.post(f"/staff/bulk/batch/{batch.pk}/confirm/")
        s.refresh_from_db()
        self.assertEqual((s.phone, s.address), ("08099999999", "New address"))

    def test_score_sheet_round_trip(self):
        lect = f.staff("lect", "Lecturer")
        course = f.courses("PHT", 1, 1)[0]
        f.allocate(course, self.sem, lect)
        a = f.student("PHT", actor=self.officer)
        b = f.student("PHT", actor=self.officer)
        for s in (a, b):
            reg.submit_registration(reg.add_courses(s, self.sem, [course], s.user), s.user)
        sheet = res.get_or_create_sheet(course, self.sem, lect)
        self.client.force_login(lect)
        tpl = self.client.get(f"/staff/bulk/scores/template/?sheet={sheet.pk}")
        self.assertEqual(tpl.status_code, 200)
        rows = [[a.matric_number, a.full_name, 25, 55, ""], [b.matric_number, b.full_name, 40, 50, ""],
                ["AFC/NOT/00/0000", "Ghost", 10, 10, ""], [a.matric_number, a.full_name, 1, 1, ""]]
        self.client.post(f"/staff/bulk/scores/?sheet={sheet.pk}", {"file": xlsx(["Matric Number", "Student Name", "CA", "Exam", "Total"], rows)})
        batch = ImportBatch.objects.get(kind="scores")
        errs = [r["errors"] for r in batch.rows]
        self.assertEqual(errs[0], [])
        self.assertTrue(any("exceeds" in e for e in errs[1]))      # CA 40 > 30
        self.assertTrue(any("not registered" in e for e in errs[2]))
        self.assertTrue(any("more than once" in e for e in errs[3]))
        self.client.post(f"/staff/bulk/batch/{batch.pk}/confirm/")
        sc = Score.objects.get(sheet=sheet, student=a)
        self.assertEqual((sc.total, sc.grade), (Decimal("80.00"), "A"))
        self.assertIsNone(Score.objects.get(sheet=sheet, student=b).total)

    def test_bulk_course_registration_on_behalf(self):
        s = f.student("CHE", actor=self.officer)
        self.client.post(f"/staff/bulk/course_registration/?semester={self.sem.pk}",
                         {"file": xlsx(["Matric Number", "Action", "Course Codes", "Submit Registration"], [[s.matric_number, "add", "ALL", "Yes"]])})
        batch = ImportBatch.objects.get()
        self.assertEqual(batch.error_count, 0, batch.rows)
        self.client.post(f"/staff/bulk/batch/{batch.pk}/confirm/")
        r = s.registrations.get(semester=self.sem)
        self.assertEqual(r.total_units, 21)  # CHEW Year One first semester
        self.assertEqual(r.status, "approved")
        self.assertTrue(all(i.via_staff for i in r.items.all()))


@override_settings(ALLOWED_HOSTS=["testserver"])
class AccessControlTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        f.load_institution()

    def test_portals_are_separated(self):
        s = f.student("PHT")
        self.client.force_login(s.user)
        self.assertEqual(self.client.get("/staff/").status_code, 403)
        self.assertEqual(self.client.get("/staff/students/").status_code, 403)
        self.assertEqual(self.client.get("/student/").status_code, 200)

    def test_role_permissions(self):
        lect = f.staff("lect", "Lecturer")
        bursar = f.staff("bursar", "Bursary Officer")
        self.client.force_login(lect)
        self.assertEqual(self.client.get("/staff/bursary/").status_code, 403)
        self.assertEqual(self.client.get("/staff/results/my-courses/").status_code, 200)
        self.client.force_login(bursar)
        self.assertEqual(self.client.get("/staff/bursary/").status_code, 200)
        self.assertEqual(self.client.get("/staff/roles/").status_code, 403)
        self.assertEqual(self.client.get("/staff/bulk/students_create/").status_code, 403)

    def test_student_cannot_see_other_students_receipt_or_invoice(self):
        from apps.bursary import services as bursary
        sess, _ = f.session_and_semester()
        a, b = f.student("PHT"), f.student("PHT")
        inv = bursary.generate_student_invoice(b, sess, None)
        self.client.force_login(a.user)
        self.assertEqual(self.client.get(f"/payments/invoice/{inv.pk}/pay/").status_code, 403)
        self.assertEqual(self.client.get(f"/payments/invoice/{inv.pk}/pdf/").status_code, 403)

    def test_login_portal_mismatch_redirects(self):
        f.staff("staffer", "Lecturer")
        r = self.client.post("/student/login/", {"username": "staffer", "password": "Passw0rd!x"})
        self.assertRedirects(r, "/staff/login/")

    def test_login_with_matric_number(self):
        s = f.student("PHT")
        r = self.client.post("/student/login/", {"username": s.matric_number, "password": "Passw0rd!x"})
        self.assertRedirects(r, "/student/")
