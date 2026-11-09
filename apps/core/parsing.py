import datetime

from django.core.exceptions import ValidationError
from django.core.validators import validate_email


def parse_date(value, label="Date", required=False):
    if value in (None, ""):
        if required:
            raise ValidationError(f"{label} is required.")
        return None
    if isinstance(value, datetime.date):
        return value
    text = str(value).strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValidationError(f"{label} '{value}' is not a valid date (use YYYY-MM-DD).")


def parse_bool(value, default=False):
    if value in (None, ""):
        return default
    return str(value).strip().lower() in ("yes", "y", "true", "1")


def parse_gender(value):
    v = str(value or "").strip().lower()
    if v in ("m", "male"):
        return "M"
    if v in ("f", "female"):
        return "F"
    if not v:
        return ""
    raise ValidationError(f"Gender '{value}' must be Male or Female.")


def clean_email(value):
    v = str(value or "").strip().lower()
    if v:
        try:
            validate_email(v)
        except ValidationError:
            raise ValidationError(f"'{value}' is not a valid e-mail address.")
    return v


def clean_phone(value):
    v = str(value or "").strip().replace(" ", "")
    if v and (len(v) < 7 or not v.lstrip("+").isdigit()):
        raise ValidationError(f"'{value}' is not a valid phone number.")
    return v
