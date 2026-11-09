"""Generic, audited CRUD screens for configuration data.

Used for everything the Super Administrator configures (departments,
programmes, sessions, fee items, grading schemes, statuses, website content...)
so each module only declares *what* is editable, not *how*.
"""
from dataclasses import dataclass, field

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import ProtectedError, Q, RestrictedError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse

from . import audit
from .permissions import staff_required


@dataclass
class Crud:
    name: str                      # url-name prefix, e.g. "department"
    model: type
    form_class: type
    permissions: tuple
    title: str                     # plural, e.g. "Departments"
    singular: str = ""
    list_display: list = field(default_factory=list)  # [(label, attr)]
    search_fields: list = field(default_factory=list)
    ordering: tuple = ()
    inlines: list = field(default_factory=list)       # [(label, formset_class)]
    can_create: bool = True
    can_delete: bool = True
    description: str = ""
    section: str = ""
    queryset_hook: object = None   # callable(qs, request) -> qs
    detail_url: object = None      # callable(obj) -> url
    namespace: str = ""
    form_template: str = "staff/crud/form.html"

    def url(self, action, pk=None):
        name = f"{self.namespace}:{self.name}_{action}" if self.namespace else f"{self.name}_{action}"
        return reverse(name, args=[pk] if pk is not None else [])

    def urls(self):
        p = self.name.replace("_", "-")
        return [
            path(f"{p}/", self.list_view(), name=f"{self.name}_list"),
            path(f"{p}/new/", self.form_view(), name=f"{self.name}_create"),
            path(f"{p}/<int:pk>/edit/", self.form_view(), name=f"{self.name}_edit"),
            path(f"{p}/<int:pk>/delete/", self.delete_view(), name=f"{self.name}_delete"),
        ]

    # ------------------------------------------------------------------
    def base_ctx(self, request):
        return {
            "crud": self,
            "title": self.title,
            "singular": self.singular or self.model._meta.verbose_name.title(),
            "list_url": self.url("list"),
            "create_url": self.url("create") if self.can_create else None,
        }

    def list_view(self):
        crud = self

        @staff_required(*crud.permissions)
        def view(request):
            qs = crud.model.objects.all()
            if crud.ordering:
                qs = qs.order_by(*crud.ordering)
            if crud.queryset_hook:
                qs = crud.queryset_hook(qs, request)
            q = request.GET.get("q", "").strip()
            if q and crud.search_fields:
                cond = Q()
                for f in crud.search_fields:
                    cond |= Q(**{f"{f}__icontains": q})
                qs = qs.filter(cond)
            page = Paginator(qs, 25).get_page(request.GET.get("page"))
            rows = []
            for obj in page:
                rows.append({
                    "obj": obj,
                    "edit_url": crud.url("edit", obj.pk),
                    "delete_url": crud.url("delete", obj.pk) if crud.can_delete else None,
                    "detail_url": crud.detail_url(obj) if crud.detail_url else None,
                })
            ctx = crud.base_ctx(request) | {"page": page, "rows": rows, "q": q,
                                            "columns": crud.list_display or [(crud.singular or "Name", "__str__")]}
            return render(request, "staff/crud/list.html", ctx)

        return view

    def form_view(self):
        crud = self

        @staff_required(*crud.permissions)
        def view(request, pk=None):
            obj = get_object_or_404(crud.model, pk=pk) if pk else None
            before = audit.snapshot(obj) if obj else {}
            form = crud.form_class(request.POST or None, request.FILES or None, instance=obj)
            formsets = [
                (label, fs_class(request.POST or None, request.FILES or None, instance=obj, prefix=f"inline{i}"))
                for i, (label, fs_class) in enumerate(crud.inlines)
            ]
            if request.method == "POST" and form.is_valid() and all(fs.is_valid() for _, fs in formsets):
                with transaction.atomic():
                    saved = form.save()
                    for _, fs in formsets:
                        fs.instance = saved
                        fs.save()
                    changes = audit.diff(before, audit.snapshot(saved))
                    audit.log(request.user, "updated" if obj else "created", saved, changes=changes)
                messages.success(request, f"{crud.singular or 'Record'} “{saved}” saved.")
                if "save_add" in request.POST:
                    return redirect(crud.url("create"))
                return redirect(crud.url("list"))
            ctx = crud.base_ctx(request) | {"form": form, "formsets": formsets, "object": obj}
            return render(request, crud.form_template, ctx)

        return view

    def delete_view(self):
        crud = self

        @staff_required(*crud.permissions)
        def view(request, pk):
            obj = get_object_or_404(crud.model, pk=pk)
            if request.method == "POST":
                label = str(obj)
                snap = audit.snapshot(obj)
                try:
                    with transaction.atomic():
                        obj.delete()
                        audit.log(request.user, "deleted", None, module=crud.model._meta.app_label,
                                  object_repr=f"{crud.model._meta.verbose_name}: {label}", changes={"deleted": snap})
                    messages.success(request, f"“{label}” deleted.")
                except (ProtectedError, RestrictedError):
                    messages.error(request, f"“{label}” is in use by other records and cannot be deleted. "
                                            "Deactivate it instead where possible.")
                return redirect(crud.url("list"))
            return render(request, "staff/crud/delete.html", crud.base_ctx(request) | {"object": obj})

        return view


def crud_urlpatterns(namespace, *cruds):
    patterns = []
    for c in cruds:
        c.namespace = namespace
        patterns += c.urls()
    return patterns
