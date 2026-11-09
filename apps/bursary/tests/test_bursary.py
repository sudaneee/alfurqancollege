import hashlib
import hmac
import json
from decimal import Decimal
from unittest import mock

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from apps.bursary import services
from apps.bursary.models import FeeItem, GatewaySettings, Invoice, Payment
from apps.core.tests import factories as f


class FeeAndInstalmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        f.load_institution()

    def setUp(self):
        self.sess, _ = f.session_and_semester()
        self.bursar = f.staff("bursar", "Bursary Officer")

    def test_programme_specific_fees_from_schedule(self):
        regular = f.student("PHT", actor=self.bursar)
        chew = f.student("CHE", actor=self.bursar)
        i1 = services.generate_student_invoice(regular, self.sess, self.bursar)
        i2 = services.generate_student_invoice(chew, self.sess, self.bursar)
        # 70,000 + 5,500 + 3,000 (matric, year 1) + 3,000 (exam)
        self.assertEqual(i1.gross_amount, Decimal("81500.00"))
        self.assertEqual(i2.gross_amount, Decimal("131500.00"))
        a1 = services.generate_student_invoice(regular, self.sess, self.bursar, stage=FeeItem.ACCEPTANCE, year=1)
        a2 = services.generate_student_invoice(chew, self.sess, self.bursar, stage=FeeItem.ACCEPTANCE, year=1)
        self.assertEqual((a1.gross_amount, a2.gross_amount), (Decimal("10000.00"), Decimal("20000.00")))

    def test_invoice_generation_is_idempotent_and_picks_up_new_items(self):
        s = f.student("NUD", actor=self.bursar)
        inv = services.generate_student_invoice(s, self.sess, self.bursar)
        again = services.generate_student_invoice(s, self.sess, self.bursar)
        self.assertEqual(inv.pk, again.pk)
        cat = FeeItem.objects.first().category
        FeeItem.objects.create(category=cat, name="New charge", amount=Decimal("1000"))
        again = services.generate_student_invoice(s, self.sess, self.bursar)
        self.assertEqual(again.gross_amount, inv.gross_amount + 1000)
        self.assertEqual(Invoice.objects.filter(student=s, session=self.sess, purpose="fees").count(), 1)

    def test_unequal_instalments_and_balance(self):
        s = f.student("PHT", actor=self.bursar)
        inv = services.generate_student_invoice(s, self.sess, self.bursar)
        services.record_offline_payment(inv, "30000", "bank_deposit", "T-1", self.bursar, verify=True)
        services.record_offline_payment(inv, "12345.50", "pos", "T-2", self.bursar, verify=True)
        inv.refresh_from_db()
        self.assertEqual(inv.amount_paid, Decimal("42345.50"))
        self.assertEqual(inv.balance, Decimal("39154.50"))
        self.assertEqual(inv.status, Invoice.PART_PAID)
        services.record_offline_payment(inv, inv.balance, "cash", "T-3", self.bursar, verify=True)
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.PAID)
        self.assertEqual(Payment.objects.filter(invoice=inv, receipt_number__isnull=False).count(), 3)

    def test_overpayment_duplicate_reference_and_full_payment_rules(self):
        s = f.student("PHT", actor=self.bursar)
        inv = services.generate_student_invoice(s, self.sess, self.bursar)
        with self.assertRaises(ValidationError):
            services.record_offline_payment(inv, inv.balance + 1, "cash", "X-1", self.bursar)
        services.record_offline_payment(inv, 100, "cash", "X-2", self.bursar)
        with self.assertRaises(ValidationError):
            services.record_offline_payment(inv, 100, "cash", "x-2", self.bursar)  # duplicate (case-insensitive)
        acc = services.generate_student_invoice(s, self.sess, self.bursar, stage=FeeItem.ACCEPTANCE, year=1)
        self.assertFalse(acc.allow_instalments)
        with self.assertRaises(ValidationError):
            services.record_offline_payment(acc, 5000, "cash", "X-3", self.bursar)

    def test_pending_offline_payment_not_counted_until_verified(self):
        s = f.student("PHT", actor=self.bursar)
        inv = services.generate_student_invoice(s, self.sess, self.bursar)
        p = services.record_offline_payment(inv, 1000, "bank_transfer", "TR-1", self.bursar)
        inv.refresh_from_db()
        self.assertEqual(inv.amount_paid, 0)
        services.verify_offline_payment(p, self.bursar)
        inv.refresh_from_db()
        self.assertEqual(inv.amount_paid, Decimal("1000"))

    def test_discount_scholarship_and_refund(self):
        s = f.student("PHT", actor=self.bursar)
        inv = services.generate_student_invoice(s, self.sess, self.bursar)
        services.add_adjustment(inv, "scholarship", 20000, "Merit", self.bursar)
        inv.refresh_from_db()
        self.assertEqual(inv.net_amount, Decimal("61500.00"))
        p = services.record_offline_payment(inv, 61500, "cash", "R-1", self.bursar, verify=True)
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.PAID)
        services.record_refund(p, 1500, "Over-billed", self.bursar)
        inv.refresh_from_db()
        self.assertEqual(inv.balance, Decimal("1500.00"))
        with self.assertRaises(ValidationError):
            services.record_refund(p, 70000, "Too much", self.bursar)


class OnlinePaymentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        f.load_institution()

    def setUp(self):
        self.sess, _ = f.session_and_semester()
        self.s = f.student("PHT", actor=None)
        self.inv = services.generate_student_invoice(self.s, self.sess, None)

    @override_settings(ALLOW_SANDBOX_GATEWAY=True)
    def test_browser_return_alone_does_not_mark_paid(self):
        p, url = services.initiate_online_payment(self.inv, 10000, self.s.user, "http://testserver/payments/callback/")
        services.confirm_online_payment(p.reference)  # no simulated success recorded with the "gateway"
        p.refresh_from_db()
        self.assertNotEqual(p.status, Payment.SUCCESSFUL)

    @override_settings(PAYSTACK_SECRET_KEY="sk_test_x")
    def test_paystack_verification_amount_and_idempotency(self):
        cfg = GatewaySettings.load()
        cfg.active_gateway = "paystack"
        cfg.save()
        with mock.patch("apps.bursary.gateways._http_json") as http:
            http.return_value = (True, {"status": True, "data": {"authorization_url": "https://paystack.test/x"}})
            p, url = services.initiate_online_payment(self.inv, 10000, self.s.user, "http://cb")
            self.assertEqual(url, "https://paystack.test/x")
            # gateway reports a smaller amount than expected -> must not succeed
            http.return_value = (True, {"status": True, "data": {"status": "success", "currency": "NGN", "amount": 500000}})
            services.confirm_online_payment(p.reference)
            p.refresh_from_db()
            self.assertEqual(p.status, Payment.PENDING)
            http.return_value = (True, {"status": True, "data": {"status": "success", "currency": "NGN", "amount": 1000000}})
            services.confirm_online_payment(p.reference, "callback")
            services.confirm_online_payment(p.reference, "webhook")  # duplicate notification
        p.refresh_from_db()
        self.inv.refresh_from_db()
        self.assertEqual(p.status, Payment.SUCCESSFUL)
        self.assertEqual(self.inv.amount_paid, Decimal("10000"))

    @override_settings(PAYSTACK_SECRET_KEY="sk_test_x")
    def test_webhook_rejects_bad_signature(self):
        body = json.dumps({"event": "charge.success", "data": {"reference": "nope"}}).encode()
        r = self.client.post("/payments/webhook/paystack/", body, content_type="application/json", HTTP_X_PAYSTACK_SIGNATURE="bad")
        self.assertEqual(r.status_code, 401)
        sig = hmac.new(b"sk_test_x", body, hashlib.sha512).hexdigest()
        r = self.client.post("/payments/webhook/paystack/", body, content_type="application/json", HTTP_X_PAYSTACK_SIGNATURE=sig)
        self.assertEqual(r.status_code, 200)
