"""Payment gateway adapters.

Each adapter implements:
    initialize(reference, amount, email, callback_url, metadata) -> (ok, authorization_url, data)
    verify(reference) -> (ok, data)   # data["_amount"] is the amount actually paid in Naira
    verify_webhook(request) -> bool   # signature check

Payments are only ever completed after a server-to-server `verify` call.
"""
import hashlib
import hmac
import json
import urllib.error
import urllib.request
from decimal import Decimal

from django.conf import settings
from django.urls import reverse

from .models import GatewaySettings


def _http_json(method, url, headers, payload=None, timeout=20):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        try:
            return False, json.loads(exc.read().decode() or "{}")
        except ValueError:
            return False, {"message": f"HTTP {exc.code}"}
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return False, {"message": str(exc)}


class PaystackGateway:
    code = "paystack"
    name = "Paystack"
    base = "https://api.paystack.co"

    @property
    def secret(self):
        return settings.PAYSTACK_SECRET_KEY

    def _headers(self):
        return {"Authorization": f"Bearer {self.secret}"}

    def initialize(self, reference, amount, email, callback_url, metadata):
        if not self.secret:
            return False, "", {"message": "PAYSTACK_SECRET_KEY is not configured"}
        ok, data = _http_json("POST", f"{self.base}/transaction/initialize", self._headers(), {
            "reference": reference, "amount": int(amount * 100), "email": email,
            "callback_url": callback_url, "currency": "NGN", "metadata": metadata,
        })
        if ok and data.get("status"):
            return True, data["data"]["authorization_url"], data
        return False, "", data

    def verify(self, reference):
        ok, data = _http_json("GET", f"{self.base}/transaction/verify/{reference}", self._headers())
        tx = data.get("data") or {}
        if ok and data.get("status") and tx.get("status") == "success" and tx.get("currency") == "NGN":
            data["_amount"] = str(Decimal(tx.get("amount", 0)) / 100)
            return True, data
        data["_final_failure"] = tx.get("status") in ("failed", "abandoned", "reversed")
        return False, data

    def verify_webhook(self, request):
        signature = request.headers.get("X-Paystack-Signature", "")
        if not self.secret or not signature:
            return False
        digest = hmac.new(self.secret.encode(), request.body, hashlib.sha512).hexdigest()
        return hmac.compare_digest(digest, signature)

    def reference_from_webhook(self, payload):
        return (payload.get("data") or {}).get("reference")


class FlutterwaveGateway:
    code = "flutterwave"
    name = "Flutterwave"
    base = "https://api.flutterwave.com/v3"

    @property
    def secret(self):
        return settings.FLUTTERWAVE_SECRET_KEY

    def _headers(self):
        return {"Authorization": f"Bearer {self.secret}"}

    def initialize(self, reference, amount, email, callback_url, metadata):
        if not self.secret:
            return False, "", {"message": "FLUTTERWAVE_SECRET_KEY is not configured"}
        ok, data = _http_json("POST", f"{self.base}/payments", self._headers(), {
            "tx_ref": reference, "amount": str(amount), "currency": "NGN", "redirect_url": callback_url,
            "customer": {"email": email}, "meta": metadata,
        })
        if ok and data.get("status") == "success":
            return True, data["data"]["link"], data
        return False, "", data

    def verify(self, reference):
        ok, data = _http_json("GET", f"{self.base}/transactions/verify_by_reference?tx_ref={reference}", self._headers())
        tx = data.get("data") or {}
        if ok and data.get("status") == "success" and tx.get("status") == "successful" and tx.get("currency") == "NGN":
            data["_amount"] = str(tx.get("amount"))
            return True, data
        data["_final_failure"] = tx.get("status") == "failed"
        return False, data

    def verify_webhook(self, request):
        expected = settings.FLUTTERWAVE_WEBHOOK_HASH
        return bool(expected) and hmac.compare_digest(request.headers.get("verif-hash", ""), expected)

    def reference_from_webhook(self, payload):
        return (payload.get("data") or {}).get("tx_ref")


class SandboxGateway:
    """Local simulator for development and demonstrations only.

    It mimics a hosted checkout page; verification reads the simulated outcome
    server-side, so the completion path is the same as for real gateways.
    Disabled automatically when ALLOW_SANDBOX_GATEWAY is false (production).
    """

    code = "sandbox"
    name = "Sandbox (test)"

    def initialize(self, reference, amount, email, callback_url, metadata):
        if not settings.ALLOW_SANDBOX_GATEWAY:
            return False, "", {"message": "Sandbox gateway is disabled"}
        return True, reverse("bursary:sandbox_checkout", args=[reference]) + f"?next={callback_url}", {"sandbox": True}

    def verify(self, reference):
        from .models import Payment, TransactionLog

        if not settings.ALLOW_SANDBOX_GATEWAY:
            return False, {"message": "Sandbox gateway is disabled"}
        log = TransactionLog.objects.filter(reference=reference, event="sandbox_outcome").order_by("-created_at").first()
        if log and log.success:
            payment = Payment.objects.get(reference=reference)
            return True, {"sandbox": True, "_amount": str(payment.amount)}
        return False, {"sandbox": True, "_final_failure": bool(log)}

    def verify_webhook(self, request):
        return False

    def reference_from_webhook(self, payload):
        return None


GATEWAYS = {g.code: g for g in (PaystackGateway(), FlutterwaveGateway(), SandboxGateway())}


def get_gateway():
    cfg = GatewaySettings.load()
    return GATEWAYS.get(cfg.active_gateway, GATEWAYS["sandbox"])


def get_gateway_by_code(code):
    return GATEWAYS.get(code) or get_gateway()
