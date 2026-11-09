"""Bursary business logic shared by the student portal, applicant portal,
staff portal, bulk imports and gateway callbacks/webhooks."""
import secrets
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core import audit
from apps.core.sequences import next_value

from .models import ZERO, Adjustment, FeeItem, Invoice, InvoiceLine, Payment, Refund, TransactionLog


def to_amount(value):
    try:
        amount = Decimal(str(value).replace(",", "").replace("₦", "").strip()).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ValidationError("Enter a valid amount.")
    if amount <= 0:
        raise ValidationError("Amount must be greater than zero.")
    return amount


def invoice_number():
    year = timezone.localdate().year
    return f"INV/{year}/{next_value(f'invoice-{year}'):06d}"


def receipt_number():
    year = timezone.localdate().year
    return f"RCT/{year}/{next_value(f'receipt-{year}'):06d}"


def new_reference(prefix="AFC"):
    return f"{prefix}-{timezone.now():%Y%m%d}-{secrets.token_hex(5).upper()}"


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------
def _apply_instalment_policy(invoice, items):
    invoice.allow_instalments = all(i.allow_instalments for i in items) if items else True
    pct = max([i.min_first_payment_percent for i in items] or [0])
    invoice.min_first_payment = (invoice.gross_amount * Decimal(pct) / 100).quantize(Decimal("0.01")) if pct else ZERO
    dues = [i.due_date for i in items if i.due_date]
    invoice.due_date = min(dues) if dues else None


def applicable_fee_items(student, session, stage=FeeItem.STUDENT, year=None):
    year = year or student.current_year
    items = FeeItem.objects.filter(stage=stage, is_active=True).select_related("category").prefetch_related("programmes")
    return [i for i in items if i.applies_to(student.programme, session, year)]


@transaction.atomic
def generate_student_invoice(student, session, actor, stage=FeeItem.STUDENT, year=None):
    """Create the session (or acceptance) invoice for a student from the configured fee schedule.

    Idempotent: returns the existing open invoice for the same purpose/session.
    Newly configured items are added to an existing unpaid invoice.
    """
    purpose = "acceptance" if stage == FeeItem.ACCEPTANCE else "fees"
    items = applicable_fee_items(student, session, stage, year)
    invoice = Invoice.objects.filter(student=student, session=session, purpose=purpose).exclude(status=Invoice.CANCELLED).first()
    if invoice is None:
        if not items:
            return None
        label = "Acceptance fee" if purpose == "acceptance" else f"{session.name} fees"
        invoice = Invoice.objects.create(
            number=invoice_number(), purpose=purpose, student=student, session=session,
            description=f"{label} — {student.programme.name} ({student.programme.level_name(year or student.current_year)})",
            created_by=actor, is_sample=student.is_sample,
        )
        audit.log(actor, "invoice_created", invoice, on_behalf_of=student.user)
    existing = set(invoice.lines.values_list("fee_item_id", flat=True))
    added = [i for i in items if i.id not in existing]
    for item in added:
        InvoiceLine.objects.create(invoice=invoice, fee_item=item, category=item.category, description=item.name, amount=item.amount)
    invoice.recalculate(save=False)
    _apply_instalment_policy(invoice, items)
    invoice.save()
    return invoice


@transaction.atomic
def ensure_application_invoice(application, actor=None):
    fee = application.period.application_fee
    if fee <= 0 or application.fee_exempt:
        return None
    inv = application.invoices.filter(purpose="application").exclude(status=Invoice.CANCELLED).first()
    if inv:
        return inv
    from .models import FeeCategory

    cat = FeeCategory.objects.filter(code="application").first()
    inv = Invoice.objects.create(
        number=invoice_number(), purpose="application", application=application, session=application.period.session,
        description=f"Application form — {application.period.name}", allow_instalments=False,
        created_by=actor, is_sample=application.is_sample,
    )
    InvoiceLine.objects.create(invoice=inv, category=cat, description="Application form fee", amount=fee)
    inv.recalculate()
    return inv


@transaction.atomic
def cancel_invoice(invoice, actor, reason):
    if invoice.payments.filter(status=Payment.SUCCESSFUL).exists():
        raise ValidationError("An invoice with successful payments cannot be cancelled. Record a refund instead.")
    invoice.status = Invoice.CANCELLED
    invoice.save(update_fields=["status"])
    audit.log(actor, "invoice_cancelled", invoice, note=reason)


@transaction.atomic
def add_adjustment(invoice, kind, amount, reason, actor, sponsor=""):
    amount = to_amount(amount)
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if amount > invoice.balance:
        raise ValidationError(f"The adjustment cannot exceed the outstanding balance (₦{invoice.balance:,.2f}).")
    adj = Adjustment.objects.create(invoice=invoice, kind=kind, amount=amount, reason=reason, sponsor=sponsor, approved_by=actor)
    invoice.recalculate()
    audit.log(actor, f"{kind}_granted", invoice, changes={"amount": str(amount), "reason": reason},
              on_behalf_of=invoice.payer_user)
    return adj


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
def validate_payment_amount(invoice, amount):
    if invoice.status == Invoice.CANCELLED:
        raise ValidationError("This invoice has been cancelled.")
    if amount > invoice.balance:
        raise ValidationError(f"Amount exceeds the outstanding balance of ₦{invoice.balance:,.2f}.")
    minimum = invoice.minimum_payment()
    if amount < minimum:
        if not invoice.allow_instalments:
            raise ValidationError("This invoice must be paid in full in a single payment.")
        raise ValidationError(f"The minimum acceptable payment now is ₦{minimum:,.2f}.")


@transaction.atomic
def record_offline_payment(invoice, amount, method, reference, actor, *, paid_at=None, note="", evidence=None,
                           verify=False, is_sample=False):
    """Staff-recorded payment (bank, POS, cash). Pending until verified unless `verify`."""
    amount = to_amount(amount)
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    validate_payment_amount(invoice, amount)
    reference = (reference or "").strip() or new_reference("OFF")
    if Payment.objects.filter(reference__iexact=reference).exists():
        raise ValidationError(f"A payment with reference '{reference}' already exists (possible duplicate).")
    payment = Payment.objects.create(
        invoice=invoice, amount=amount, method=method, reference=reference, status=Payment.PENDING,
        paid_at=paid_at or timezone.now(), payer_note=note, initiated_by=actor, is_sample=is_sample,
    )
    if evidence:
        payment.evidence = evidence
        payment.save(update_fields=["evidence"])
    audit.log(actor, "payment_recorded", payment, changes={"amount": str(amount), "method": method},
              on_behalf_of=invoice.payer_user)
    if verify:
        verify_offline_payment(payment, actor)
    return payment


@transaction.atomic
def verify_offline_payment(payment, actor, approve=True, note=""):
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status != Payment.PENDING:
        raise ValidationError("Only pending payments can be verified.")
    if approve:
        _mark_successful(payment, verified_by=actor)
    else:
        payment.status = Payment.FAILED
        payment.verified_by, payment.verified_at = actor, timezone.now()
        payment.save()
    audit.log(actor, "payment_verified" if approve else "payment_rejected", payment, note=note,
              on_behalf_of=payment.invoice.payer_user)
    return payment


def _mark_successful(payment, verified_by=None, gateway_data=None):
    """Idempotently mark a (locked) payment successful, issue a receipt and update the invoice."""
    if payment.status == Payment.SUCCESSFUL:
        return payment
    invoice = Invoice.objects.select_for_update().get(pk=payment.invoice_id)
    payment.status = Payment.SUCCESSFUL
    payment.receipt_number = payment.receipt_number or receipt_number()
    payment.paid_at = payment.paid_at or timezone.now()
    payment.verified_by = verified_by
    payment.verified_at = timezone.now()
    if gateway_data is not None:
        payment.gateway_response = gateway_data
    payment.save()
    invoice.recalculate()
    _after_payment(payment, invoice)
    return payment


def _after_payment(payment, invoice):
    from apps.notifications.services import notify

    user = invoice.payer_user
    notify(user, "payment_received", {"amount": f"₦{payment.amount:,.2f}", "reference": payment.reference,
                                      "receipt": payment.receipt_number, "balance": f"₦{invoice.balance:,.2f}",
                                      "description": invoice.description})
    if invoice.purpose == "application" and invoice.status == Invoice.PAID and invoice.application_id:
        from apps.admissions.models import ApplicationEvent
        ApplicationEvent.objects.create(application=invoice.application, action="Application fee paid",
                                        note=payment.reference, actor=user)


@transaction.atomic
def initiate_online_payment(invoice, amount, actor, callback_url):
    from .gateways import get_gateway

    amount = to_amount(amount)
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    validate_payment_amount(invoice, amount)
    gateway = get_gateway()
    reference = new_reference("AFC")
    payment = Payment.objects.create(invoice=invoice, amount=amount, method="online", reference=reference,
                                     gateway=gateway.code, status=Payment.PENDING, initiated_by=actor,
                                     is_sample=invoice.is_sample)
    payer = invoice.payer_user
    email = (payer.email if payer and payer.email else "payments@alfurqancollege.com.ng")
    ok, url, data = gateway.initialize(reference=reference, amount=amount, email=email, callback_url=callback_url,
                                       metadata={"invoice": invoice.number, "payer": invoice.payer_reference})
    TransactionLog.objects.create(payment=payment, reference=reference, gateway=gateway.code, event="initialize",
                                  success=ok, payload=data, message="" if ok else str(data.get("message", ""))[:255])
    audit.log(actor, "online_payment_initiated", payment, changes={"amount": str(amount)}, on_behalf_of=payer)
    if not ok:
        payment.status = Payment.FAILED
        payment.save(update_fields=["status"])
        raise ValidationError("The payment gateway could not start this payment. Please try again later.")
    return payment, url


def confirm_online_payment(reference, source="callback"):
    """Verify a transaction directly with the gateway (never trust the browser)."""
    from .gateways import get_gateway_by_code

    with transaction.atomic():
        payment = Payment.objects.select_for_update().filter(reference=reference).first()
        if payment is None:
            TransactionLog.objects.create(reference=reference, gateway="unknown", event=f"{source}_unknown_ref")
            return None
        if payment.status == Payment.SUCCESSFUL:
            TransactionLog.objects.create(payment=payment, reference=reference, gateway=payment.gateway,
                                          event=f"{source}_duplicate", success=True, message="Already confirmed")
            return payment
        gateway = get_gateway_by_code(payment.gateway)
        ok, data = gateway.verify(reference)
        paid_amount = data.get("_amount")
        valid = ok and paid_amount is not None and Decimal(str(paid_amount)) >= payment.amount
        TransactionLog.objects.create(payment=payment, reference=reference, gateway=payment.gateway,
                                      event=f"{source}_verify", success=valid, payload=data,
                                      message="" if valid else "Verification failed or amount mismatch")
        if valid:
            _mark_successful(payment, gateway_data=data)
            audit.log(None, "online_payment_confirmed", payment, note=f"via {source}")
        elif data.get("_final_failure"):
            payment.status = Payment.FAILED
            payment.gateway_response = data
            payment.save(update_fields=["status", "gateway_response"])
        return payment


@transaction.atomic
def record_refund(payment, amount, reason, actor, reference=""):
    amount = to_amount(amount)
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status != Payment.SUCCESSFUL:
        raise ValidationError("Only successful payments can be refunded.")
    refund = Refund(payment=payment, amount=amount, reason=reason, reference=reference, processed_by=actor)
    refund.full_clean()
    refund.save()
    payment.invoice.recalculate()
    audit.log(actor, "refund_recorded", payment, changes={"amount": str(amount), "reason": reason},
              on_behalf_of=payment.invoice.payer_user)
    return refund


def student_financial_summary(student):
    invoices = list(student.invoices.exclude(status=Invoice.CANCELLED))
    total = sum((i.net_amount for i in invoices), ZERO)
    paid = sum((i.amount_paid for i in invoices), ZERO)
    return {"invoices": invoices, "total": total, "paid": paid, "balance": max(ZERO, total - paid)}
