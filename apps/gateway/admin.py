from django.contrib import admin

from .models import RequestLog, SemanticCacheEntry


@admin.register(RequestLog)
class RequestLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "org",
        "external_tenant_id",
        "model_served",
        "provider_served",
        "status",
        "cost_usd",
        "latency_ms",
    )
    list_filter = ("org", "status")
    search_fields = ("external_tenant_id", "model_requested", "model_served")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SemanticCacheEntry)
class SemanticCacheEntryAdmin(admin.ModelAdmin):
    list_display = ("org", "model_alias", "hit_count", "created_at")
    list_filter = ("org", "model_alias")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
