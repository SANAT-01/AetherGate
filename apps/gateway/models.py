import uuid

from django.db import models
from pgvector.django import HnswIndex, VectorField


class SemanticCacheEntry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey(
        "tenants.Organization", on_delete=models.CASCADE, related_name="cache_entries"
    )
    model_alias = models.CharField(max_length=255)
    prompt_text = models.TextField()
    embedding = VectorField(dimensions=384)
    response_payload = models.JSONField()
    hit_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            HnswIndex(
                name="cache_embedding_hnsw_idx",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ]

    def __str__(self) -> str:
        return f"{self.org_id}:{self.model_alias}:{self.id}"


class RequestLog(models.Model):
    class Status(models.TextChoices):
        SUCCESS = "SUCCESS"
        CACHE_HIT = "CACHE_HIT"
        FALLBACK_SUCCESS = "FALLBACK_SUCCESS"
        FAILED = "FAILED"
        BUDGET_EXCEEDED = "BUDGET_EXCEEDED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey(
        "tenants.Organization",
        on_delete=models.CASCADE,
        related_name="request_logs",
        null=True,
        blank=True,
    )
    external_tenant_id = models.CharField(max_length=255, blank=True, default="")
    api_key = models.ForeignKey(
        "tenants.GatewayAPIKey",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="request_logs",
    )
    model_requested = models.CharField(max_length=255)
    model_served = models.CharField(max_length=255, blank=True, default="")
    provider_served = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=32, choices=Status.choices)
    prompt_tokens = models.PositiveIntegerField(null=True, blank=True)
    completion_tokens = models.PositiveIntegerField(null=True, blank=True)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    saved_usd = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["org", "created_at"]),
            models.Index(fields=["org", "external_tenant_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.id} [{self.status}]"
