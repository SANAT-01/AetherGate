from datetime import datetime

from django.db.models import Aggregate, FloatField, Sum
from django.db.models.functions import TruncDate

from apps.gateway.models import RequestLog
from apps.tenants.models import Organization


class PercentileCont(Aggregate):
    # django.contrib.postgres.aggregates has no PercentileCont in this Django
    # version — this wraps Postgres's native percentile_cont() ordered-set
    # aggregate directly (`percentile_cont(0.95) WITHIN GROUP (ORDER BY ...)`).
    function = "percentile_cont"
    template = "%(function)s(%(percentile)s) WITHIN GROUP (ORDER BY %(expressions)s)"
    output_field = FloatField()

    def __init__(self, expression, percentile: float, **extra):
        super().__init__(expression, percentile=percentile, **extra)


def _real_attempts(org: Organization, since: datetime):
    # Excludes BUDGET_EXCEEDED and other pre-auth rejections (which never get
    # a row at all, see apps/gateway/api.py Step 0) — those aren't real
    # upstream attempts and would skew spend/latency/cache numbers.
    return RequestLog.objects.filter(org=org, created_at__gte=since).exclude(
        status=RequestLog.Status.BUDGET_EXCEEDED
    )


def get_spend_summary(org: Organization, since: datetime) -> dict:
    qs = _real_attempts(org, since)
    total = qs.aggregate(total_cost_usd=Sum("cost_usd"))["total_cost_usd"] or 0

    by_tenant = list(
        qs.values("external_tenant_id").annotate(cost_usd=Sum("cost_usd")).order_by("-cost_usd")
    )
    by_day = list(
        qs.annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(cost_usd=Sum("cost_usd"))
        .order_by("day")
    )

    return {
        "total_cost_usd": total,
        "by_tenant": by_tenant,
        "by_day": by_day,
    }


def get_cache_savings_summary(org: Organization, since: datetime) -> dict:
    qs = _real_attempts(org, since)
    total_requests = qs.count()
    cache_hits = qs.filter(status=RequestLog.Status.CACHE_HIT)
    cache_hit_count = cache_hits.count()
    total_saved_usd = cache_hits.aggregate(total=Sum("saved_usd"))["total"] or 0
    hit_rate = (cache_hit_count / total_requests) if total_requests else 0.0

    return {
        "total_requests": total_requests,
        "cache_hit_count": cache_hit_count,
        "cache_hit_rate": hit_rate,
        "total_saved_usd": total_saved_usd,
    }


def get_latency_percentiles(org: Organization, since: datetime) -> dict:
    qs = _real_attempts(org, since).filter(latency_ms__isnull=False)
    result = qs.aggregate(
        p50=PercentileCont("latency_ms", 0.5),
        p95=PercentileCont("latency_ms", 0.95),
        p99=PercentileCont("latency_ms", 0.99),
    )
    return {
        "sample_count": qs.count(),
        "p50_ms": result["p50"],
        "p95_ms": result["p95"],
        "p99_ms": result["p99"],
    }
