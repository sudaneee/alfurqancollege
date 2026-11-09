"""Technical fallback admin. Everyday administration happens in the Staff Portal,
which enforces the business rules and audit trail; this site is read-mostly."""
from django.apps import apps
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from apps.accounts.models import User

from .models import AuditLog


@admin.register(User)
class AlfurqanUserAdmin(UserAdmin):
    list_display = ("username", "email", "first_name", "last_name", "user_type", "is_active", "is_sample")
    list_filter = ("user_type", "is_active", "is_superuser", "groups", "is_sample")
    fieldsets = UserAdmin.fieldsets + (("Alfurqan", {"fields": ("user_type", "other_names", "phone", "must_change_password", "is_sample")}),)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "actor", "action", "object_repr", "on_behalf_of")
    list_filter = ("module", "action")
    search_fields = ("object_repr", "note", "actor__username")

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False


for label in ("core", "accounts", "website", "academics", "admissions", "students", "registration", "results", "bursary", "notifications"):
    for model in apps.get_app_config(label).get_models():
        if not admin.site.is_registered(model) and model._meta.model_name != "permissionanchor":
            admin.site.register(model)
