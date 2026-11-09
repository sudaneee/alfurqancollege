"""Audit trail service. Every important change goes through `log()`."""
import datetime
import decimal

from django.db import models
from django.db.models.fields.files import FieldFile

from .middleware import client_ip, get_current_request
from .models import AuditLog


def _jsonable(value):
    if isinstance(value, models.Model):
        return str(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, FieldFile):
        return value.name or ""
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def snapshot(instance, fields=None):
    """Return a JSON-safe dict of the instance's concrete field values."""
    data = {}
    for f in instance._meta.concrete_fields:
        if fields and f.name not in fields:
            continue
        if f.name == "password":
            continue
        data[f.name] = _jsonable(getattr(instance, f.name, None))
    return data


def diff(before, after):
    return {k: [before.get(k), v] for k, v in after.items() if before.get(k) != v}


def log(actor, action, obj=None, *, module="", changes=None, note="", on_behalf_of=None, object_repr=None):
    request = get_current_request()
    if actor is not None and not getattr(actor, "is_authenticated", False):
        actor = None
    if on_behalf_of is not None and actor is not None and on_behalf_of.pk == actor.pk:
        on_behalf_of = None
    entry = AuditLog(
        actor=actor,
        action=action,
        module=module or (obj._meta.app_label if obj is not None else ""),
        changes=changes or {},
        note=note or "",
        on_behalf_of=on_behalf_of,
        ip_address=client_ip(request),
    )
    if obj is not None:
        entry.object_type = obj._meta.label
        entry.object_id = str(obj.pk)
        entry.object_repr = (object_repr or str(obj))[:255]
    elif object_repr:
        entry.object_repr = object_repr[:255]
    entry.save()
    return entry
