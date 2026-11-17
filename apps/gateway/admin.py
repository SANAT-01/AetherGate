from datetime import timedelta

from django.contrib import admin
from django.template.response import TemplateResponse
from django.urls import path
from django.utils import timezone

from apps.analytics.queries import (
    get_cache_savings_summary,
    get_latency_percentiles,
    get_spend_summary,
)
from apps.tenants.models import Organization

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
    change_list_template = "admin/gateway/requestlog/change_list.html"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        dashboard_url = path(
            "dashboard/", self.admin_site.admin_view(self.dashboard_view), name="finops_dashboard"
        )
        return [dashboard_url, *super().get_urls()]

    def dashboard_view(self, request):
        days = int(request.GET.get("days", 7))
        since = timezone.now() - timedelta(days=days)
        selected_org_id = request.GET.get("org")

        orgs = list(Organization.objects.order_by("name"))
        selected_org = None
        if selected_org_id:
            selected_org = next((o for o in orgs if str(o.id) == selected_org_id), None)
        elif orgs:
            selected_org = orgs[0]

        context = {
            **self.admin_site.each_context(request),
            "title": "FinOps dashboard",
            "orgs": orgs,
            "selected_org": selected_org,
            "days": days,
        }
        if selected_org is not None:
            context["spend"] = get_spend_summary(selected_org, since)
            context["cache_savings"] = get_cache_savings_summary(selected_org, since)
            context["latency"] = get_latency_percentiles(selected_org, since)

        return TemplateResponse(request, "admin/gateway/requestlog/dashboard.html", context)


@admin.register(SemanticCacheEntry)
class SemanticCacheEntryAdmin(admin.ModelAdmin):
    list_display = ("org", "model_alias", "hit_count", "created_at")
    list_filter = ("org", "model_alias")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
