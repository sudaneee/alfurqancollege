from django.core.exceptions import ValidationError

from apps.core import parsing
from apps.core.bulk import BaseImporter, Column, RowError, register
from apps.core.permissions import has_perm

from . import services
from .models import Invoice, Payment

METHODS = [m for m, _ in Payment.METHOD_CHOICES if m != "online"]


@register
class PaymentImporter(BaseImporter):
    kind = "payments"
    title = "Record payments in bulk"
    description = ("Record bank, POS or cash payments for many students (e.g. from a bank statement). Each payment "
                   "is matched to an invoice by invoice number, or to the student's oldest outstanding invoice by "
                   "matric number. Duplicate references are rejected.")
    permissions = ("record_payments",)
    back_url_name = "bursary:payments"
    columns = [
        Column("invoice_number", "Invoice Number", False, "", help="Optional when Matric Number is given"),
        Column("matric_number", "Matric Number", False, "AFC/PHT/25/0001"),
        Column("amount", "Amount", True, 35000),
        Column("method", "Method", True, "bank_deposit", choices=METHODS),
        Column("reference", "Bank / Teller Reference", True, "TELLER-0001"),
        Column("paid_on", "Date Paid", False, "2026-01-15", help="YYYY-MM-DD"),
        Column("verified", "Mark Verified", False, "No", choices=["Yes", "No"],
               help="Only applied if you have payment-verification permission"),
    ]

    def prepare(self, context):
        return {"refs": set()}

    def _invoice(self, data):
        number = str(data.get("invoice_number") or "").strip()
        if number:
            inv = Invoice.objects.filter(number__iexact=number).first()
            if not inv:
                raise RowError(f"Invoice {number} not found.")
            return inv
        matric = str(data.get("matric_number") or "").strip()
        if not matric:
            raise RowError("Provide an Invoice Number or a Matric Number.")
        inv = (Invoice.objects.filter(student__matric_number__iexact=matric, status__in=[Invoice.UNPAID, Invoice.PART_PAID])
               .order_by("created_at").first())
        if not inv:
            raise RowError(f"{matric} has no outstanding invoice.")
        return inv

    def validate_row(self, data, context, state):
        try:
            inv = self._invoice(data)
            amount = services.to_amount(data["amount"])
            services.validate_payment_amount(inv, amount)
            parsing.parse_date(data.get("paid_on"), "Date Paid")
        except ValidationError as exc:
            return exc.messages, "", {}
        method = str(data["method"]).strip().lower()
        if method not in METHODS:
            return [f"Method must be one of {', '.join(METHODS)}."], "", {}
        ref = str(data["reference"]).strip()
        if ref.upper() in state["refs"]:
            return [f"Reference {ref} appears more than once in this file."], "", {}
        state["refs"].add(ref.upper())
        if Payment.objects.filter(reference__iexact=ref).exists():
            return [f"Reference {ref} has already been recorded."], "", {}
        return [], "create", {"payment": [f"{inv.number} balance ₦{inv.balance:,.2f}", f"₦{amount:,.2f}"]}

    def apply_row(self, data, context, actor, state):
        import datetime

        from django.utils import timezone

        inv = self._invoice(data)
        paid_on = parsing.parse_date(data.get("paid_on"), "Date Paid")
        paid_at = timezone.make_aware(datetime.datetime.combine(paid_on, datetime.time(12))) if paid_on else None
        verify = parsing.parse_bool(data.get("verified")) and has_perm(actor, "verify_payments")
        p = services.record_offline_payment(inv, data["amount"], str(data["method"]).strip().lower(),
                                            str(data["reference"]).strip(), actor, paid_at=paid_at, verify=verify)
        return f"{p.get_status_display()} — {inv.number}"
