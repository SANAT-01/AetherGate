import uuid

from django.db import models


class Organization(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name


class GatewayAPIKey(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="api_keys")
    name = models.CharField(max_length=255)
    key_prefix = models.CharField(max_length=12, db_index=True)
    key_hash = models.CharField(max_length=128, unique=True)
    is_active = models.BooleanField(default=True)
    rate_limit_per_minute = models.PositiveIntegerField(default=60)
    routing_policy = models.ForeignKey(
        "routing.RoutingPolicy",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="api_keys",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.org.slug}:{self.key_prefix}***"


class EndCustomerBudget(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="customer_budgets")
    external_tenant_id = models.CharField(max_length=255, db_index=True)
    daily_limit_usd = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    monthly_limit_usd = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    is_blocked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["org", "external_tenant_id"], name="uniq_org_external_tenant"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.org.slug}/{self.external_tenant_id}"
