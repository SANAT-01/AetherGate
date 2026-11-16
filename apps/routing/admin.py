from django import forms
from django.contrib import admin
from pydantic import ValidationError

from .crypto import encrypt_api_key
from .models import ModelPricing, ProviderCredential, RoutingPolicy
from .schemas import RoutingRules


class ProviderCredentialAdminForm(forms.ModelForm):
    # Admins type the raw provider key here; it's encrypted on save and
    # never displayed back, mirroring GatewayAPIKeyAdmin's one-time reveal.
    raw_api_key = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Enter to set/replace the stored key. Leave blank to keep the existing one.",
    )

    class Meta:
        model = ProviderCredential
        fields = ["org", "provider", "base_url", "is_active"]

    def save(self, commit: bool = True) -> ProviderCredential:
        instance = super().save(commit=False)
        raw_api_key = self.cleaned_data.get("raw_api_key")
        if raw_api_key:
            instance.encrypted_api_key = encrypt_api_key(raw_api_key)
        if commit:
            instance.save()
        return instance


@admin.register(ProviderCredential)
class ProviderCredentialAdmin(admin.ModelAdmin):
    form = ProviderCredentialAdminForm
    list_display = ("org", "provider", "is_active", "created_at")
    list_filter = ("org", "provider", "is_active")


class RoutingPolicyAdminForm(forms.ModelForm):
    class Meta:
        model = RoutingPolicy
        fields = ["org", "name", "strategy", "rules_json", "cache_enabled", "similarity_threshold"]

    def clean_rules_json(self) -> dict:
        rules_json = self.cleaned_data["rules_json"]
        if rules_json:
            try:
                RoutingRules.model_validate(rules_json)
            except ValidationError as exc:
                raise forms.ValidationError(str(exc)) from exc
        return rules_json


@admin.register(RoutingPolicy)
class RoutingPolicyAdmin(admin.ModelAdmin):
    form = RoutingPolicyAdminForm
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
