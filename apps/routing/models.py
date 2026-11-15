import uuid

from django.db import models


class ProviderCredential(models.Model):
    PROVIDER_CHOICES = [
        ("freellmapi", "FreeLLMAPI"),
        ("openai", "OpenAI"),
        ("anthropic", "Anthropic"),
        ("gemini", "Gemini"),
        ("ollama", "Ollama"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey(
        "tenants.Organization", on_delete=models.CASCADE, related_name="provider_credentials"
    )
    provider = models.CharField(max_length=32, choices=PROVIDER_CHOICES)
    encrypted_api_key = models.TextField(blank=True, default="")
    base_url = models.URLField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.org.slug}:{self.provider}"


class RoutingPolicy(models.Model):
    STRATEGY_CHOICES = [
        ("fallback", "Fallback Chain"),
        ("cost_optimized", "Cost Optimized"),
        ("latency", "Latency Optimized"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey(
        "tenants.Organization", on_delete=models.CASCADE, related_name="routing_policies"
    )
    name = models.CharField(max_length=255)
    strategy = models.CharField(max_length=32, choices=STRATEGY_CHOICES, default="fallback")
    rules_json = models.JSONField(default=dict, blank=True)
    cache_enabled = models.BooleanField(default=False)
    similarity_threshold = models.FloatField(default=0.95)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.org.slug}:{self.name}"


class ModelPricing(models.Model):
    model_name = models.CharField(max_length=255, unique=True)
    provider = models.CharField(max_length=32)
    input_cost_per_1m_tokens = models.DecimalField(max_digits=10, decimal_places=6)
    output_cost_per_1m_tokens = models.DecimalField(max_digits=10, decimal_places=6)

    def __str__(self) -> str:
        return self.model_name
