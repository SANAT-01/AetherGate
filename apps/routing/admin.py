from django.contrib import admin

from .models import ModelPricing, ProviderCredential, RoutingPolicy


@admin.register(ProviderCredential)
class ProviderCredentialAdmin(admin.ModelAdmin):
    list_display = ("org", "provider", "is_active", "created_at")
    list_filter = ("org", "provider", "is_active")


@admin.register(RoutingPolicy)
class RoutingPolicyAdmin(admin.ModelAdmin):
    list_display = ("org", "name", "strategy", "cache_enabled", "similarity_threshold")
    list_filter = ("org", "strategy")


@admin.register(ModelPricing)
class ModelPricingAdmin(admin.ModelAdmin):
    list_display = (
        "model_name",
        "provider",
        "input_cost_per_1m_tokens",
        "output_cost_per_1m_tokens",
    )
    list_filter = ("provider",)
