from datetime import date
from decimal import Decimal

from ninja import Schema


class SpendByTenant(Schema):
    external_tenant_id: str
    cost_usd: Decimal | None = None


class SpendByDay(Schema):
    day: date
    cost_usd: Decimal | None = None


class SpendSummaryResponse(Schema):
    total_cost_usd: Decimal
    by_tenant: list[SpendByTenant]
    by_day: list[SpendByDay]


class CacheSavingsSummaryResponse(Schema):
    total_requests: int
    cache_hit_count: int
    cache_hit_rate: float
    total_saved_usd: Decimal


class LatencyPercentilesResponse(Schema):
    sample_count: int
    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None
