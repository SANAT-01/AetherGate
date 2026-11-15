import hashlib
import secrets

from django.contrib import admin

from .models import EndCustomerBudget, GatewayAPIKey, Organization


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "created_at")
    search_fields = ("name", "slug")


@admin.register(GatewayAPIKey)
class GatewayAPIKeyAdmin(admin.ModelAdmin):
    list_display = ("org", "name", "key_prefix", "is_active", "created_at")
    list_filter = ("org", "is_active")
    readonly_fields = ("key_prefix", "key_hash")
    fields = ("org", "name", "is_active", "routing_policy", "key_prefix", "key_hash")

    def save_model(self, request, obj, form, change):
        if not change:
            raw_key = f"agw_live_{secrets.token_hex(24)}"
            obj.key_prefix = raw_key[:12]
            obj.key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
            super().save_model(request, obj, form, change)
            self.message_user(
                request,
                f"API key created. Copy it now, it will not be shown again: {raw_key}",
            )
        else:
            super().save_model(request, obj, form, change)


@admin.register(EndCustomerBudget)
class EndCustomerBudgetAdmin(admin.ModelAdmin):
    list_display = (
        "org",
        "external_tenant_id",
        "daily_limit_usd",
        "monthly_limit_usd",
        "is_blocked",
    )
    list_filter = ("org", "is_blocked")
    search_fields = ("external_tenant_id",)
