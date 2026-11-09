"""Concurrency-safe running numbers (invoice, receipt, application numbers)."""
from django.db import transaction


def next_value(key):
    from apps.bursary.models import NumberSequence

    with transaction.atomic():
        seq, _ = NumberSequence.objects.select_for_update().get_or_create(key=key)
        seq.last += 1
        seq.save(update_fields=["last"])
        return seq.last
