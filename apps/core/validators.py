import os

from django.core.exceptions import ValidationError

ALLOWED_DOCUMENT_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

# Magic-number signatures so a renamed executable cannot pass as a document.
_SIGNATURES = {
    ".pdf": [b"%PDF"],
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".png": [b"\x89PNG"],
    ".webp": [b"RIFF"],
}


def _max_bytes():
    try:
        from apps.core.models import SiteSettings
        return SiteSettings.load().max_document_size_mb * 1024 * 1024
    except Exception:
        return 5 * 1024 * 1024


def _check(f, allowed):
    ext = os.path.splitext(f.name)[1].lower()
    if ext not in allowed:
        raise ValidationError(f"Unsupported file type. Allowed: {', '.join(sorted(allowed))}.")
    limit = _max_bytes()
    if f.size > limit:
        raise ValidationError(f"File is too large. Maximum size is {limit // (1024 * 1024)} MB.")
    head = f.read(8)
    f.seek(0)
    if not any(head.startswith(sig) for sig in _SIGNATURES.get(ext, [b""])):
        raise ValidationError("The file content does not match its extension.")


def validate_document(f):
    _check(f, ALLOWED_DOCUMENT_EXTENSIONS)


def validate_image(f):
    _check(f, ALLOWED_IMAGE_EXTENSIONS)
