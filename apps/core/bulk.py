"""Generic Excel bulk-operation framework.

Each importer declares its columns and implements `validate_row` and
`apply_row`. The framework provides the full staff workflow used by every
bulk operation in the platform:

    download template → upload → validate → preview → confirm → summary
                                                     └→ download failed rows

Raw uploaded rows are stored on an ImportBatch. On confirmation every row is
validated again (data may have changed since the preview) and only valid rows
are applied, each inside its own savepoint within one transaction.
"""
from dataclasses import dataclass, field

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from . import audit
from .models import ImportBatch
from .permissions import has_any

IMPORTERS = {}


def register(cls):
    IMPORTERS[cls.kind] = cls
    return cls


def get_importer(kind, actor=None):
    cls = IMPORTERS.get(kind)
    if cls is None:
        return None
    return cls(actor)


@dataclass
class Column:
    key: str
    label: str
    required: bool = False
    example: object = ""
    help: str = ""
    choices: list = field(default_factory=list)


class RowError(Exception):
    pass


class BaseImporter:
    kind = ""
    title = ""
    description = ""
    permissions = ()
    columns = []
    back_url_name = "core:dashboard"
    context_keys = ()  # querystring keys copied into the batch context

    def __init__(self, actor=None):
        self.actor = actor  # the staff member running the import (used by permission-aware rules)

    # ---- access & context ---------------------------------------------
    def check_access(self, user, context):
        if self.permissions and not has_any(user, *self.permissions):
            raise PermissionDenied("You do not have permission for this bulk operation.")

    def context_label(self, context):
        return ""

    def clean_context(self, params, user):
        return {k: params.get(k) for k in self.context_keys if params.get(k)}

    # ---- template -------------------------------------------------------
    def headers(self):
        return [c.label for c in self.columns]

    def template_rows(self, context):
        return [[c.example for c in self.columns]]

    def notes(self, context):
        lines = [
            "Do not rename or reorder the column headings in row 1.",
            "Columns marked * are required.",
            "Delete the example row before uploading if it is not real data.",
        ]
        for c in self.columns:
            text = f"{c.label}{' *' if c.required else ''}: {c.help or ''}".rstrip(": ")
            if c.choices:
                text += f" Allowed values: {', '.join(map(str, c.choices))}."
            lines.append(text)
        return lines

    def template_filename(self, context):
        return f"{self.kind}_template.xlsx"

    # ---- validation -----------------------------------------------------
    def prepare(self, context):
        """Return a mutable state dict shared across rows (caches, duplicates)."""
        return {}

    def key_map(self):
        from .excel import normalise_header
        return {normalise_header(c.label.replace("*", "")): c.key for c in self.columns} | {c.key: c.key for c in self.columns}

    def map_row(self, raw):
        km = self.key_map()
        data = {}
        for k, v in raw.items():
            if k == "_row":
                continue
            target = km.get(k)
            if target:
                data[target] = "" if v is None else v
        for c in self.columns:
            data.setdefault(c.key, "")
        return data

    def check_required(self, data):
        return [f"{c.label} is required." for c in self.columns if c.required and str(data.get(c.key, "")).strip() == ""]

    def validate_row(self, data, context, state):
        """Return (errors, action, changes). action: 'create' | 'update' | 'skip'."""
        raise NotImplementedError

    def apply_row(self, data, context, actor, state):
        """Apply a validated row. Return a short result message."""
        raise NotImplementedError

    def after_apply(self, batch, actor):
        pass

    # ---- orchestration --------------------------------------------------
    def run_validation(self, raw_rows, context):
        state = self.prepare(context)
        results = []
        for raw in raw_rows:
            data = self.map_row(raw)
            errors = self.check_required(data)
            action, changes = "", {}
            if not errors:
                try:
                    errors, action, changes = self.validate_row(data, context, state)
                except RowError as exc:
                    errors = [str(exc)]
            results.append({
                "row": raw.get("_row"),
                "data": {k: (str(v) if v is not None else "") for k, v in data.items()},
                "errors": list(errors or []),
                "action": action or "",
                "changes": changes or {},
                "result": "",
            })
        return results

    def apply(self, batch, actor):
        self.actor = actor
        raw_rows = [dict(r["data"], _row=r["row"]) for r in batch.rows]
        validated = self.run_validation(raw_rows, batch.context)
        state = self.prepare(batch.context)
        applied = failed = skipped = 0
        with transaction.atomic():
            for row in validated:
                if row["errors"]:
                    failed += 1
                    continue
                if row["action"] == "skip":
                    skipped += 1
                    row["result"] = "No changes"
                    continue
                try:
                    with transaction.atomic():
                        row["result"] = self.apply_row(row["data"], batch.context, actor, state) or "Done"
                    applied += 1
                except RowError as exc:
                    row["errors"] = [str(exc)]
                    failed += 1
                except Exception as exc:  # unexpected: record and continue with other rows
                    row["errors"] = [f"Could not be saved: {exc}"]
                    failed += 1
            batch.rows = validated
            batch.status = ImportBatch.STATUS_APPLIED
            batch.applied_at = timezone.now()
            batch.summary = {"total": len(validated), "applied": applied, "failed": failed, "skipped": skipped}
            batch.save()
            audit.log(actor, f"bulk_{self.kind}", batch, module="bulk", changes=batch.summary,
                      note=f"{self.title}: {batch.file_name} {self.context_label(batch.context)}".strip())
            self.after_apply(batch, actor)
        return batch.summary
