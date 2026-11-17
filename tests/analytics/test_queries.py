from datetime import timedelta

import pytest
from django.utils import timezone

from apps.analytics.queries import (
    get_cache_savings_summary,
    get_latency_percentiles,
    get_spend_summary,
)
from apps.gateway.models import RequestLog
from tests.factories import create_org, create_request_log


@pytest.mark.django_db
def test_spend_summary_sums_cost_by_tenant_and_day():
    org = create_org()
    now = timezone.now()
    create_request_log(org, external_tenant_id="acme-corp", cost_usd=1.5, created_at=now)
    create_request_log(org, external_tenant_id="acme-corp", cost_usd=0.5, created_at=now)
    create_request_log(org, external_tenant_id="other-corp", cost_usd=2.0, created_at=now)

    summary = get_spend_summary(org, now - timedelta(days=1))

    assert summary["total_cost_usd"] == 4.0
    by_tenant = {row["external_tenant_id"]: row["cost_usd"] for row in summary["by_tenant"]}
    assert by_tenant["acme-corp"] == 2.0
    assert by_tenant["other-corp"] == 2.0
    assert len(summary["by_day"]) == 1


@pytest.mark.django_db
def test_spend_summary_excludes_budget_exceeded_rows():
    org = create_org()
    now = timezone.now()
    create_request_log(org, cost_usd=5.0, created_at=now)
    create_request_log(org, status=RequestLog.Status.BUDGET_EXCEEDED, cost_usd=None, created_at=now)

    summary = get_spend_summary(org, now - timedelta(days=1))

    assert summary["total_cost_usd"] == 5.0


@pytest.mark.django_db
def test_cache_savings_summary_with_no_cache_hits():
    org = create_org()
    now = timezone.now()
    create_request_log(org, cost_usd=1.0, created_at=now)
    create_request_log(org, cost_usd=1.0, created_at=now)

    summary = get_cache_savings_summary(org, now - timedelta(days=1))

    assert summary["total_requests"] == 2
    assert summary["cache_hit_count"] == 0
    assert summary["cache_hit_rate"] == 0.0
    assert summary["total_saved_usd"] == 0


@pytest.mark.django_db
def test_cache_savings_summary_with_hits():
    org = create_org()
    now = timezone.now()
    create_request_log(org, status=RequestLog.Status.SUCCESS, cost_usd=1.0, created_at=now)
    create_request_log(
        org, status=RequestLog.Status.CACHE_HIT, saved_usd=0.75, cost_usd=0, created_at=now
    )

    summary = get_cache_savings_summary(org, now - timedelta(days=1))

    assert summary["total_requests"] == 2
    assert summary["cache_hit_count"] == 1
    assert summary["cache_hit_rate"] == 0.5
    assert summary["total_saved_usd"] == 0.75


@pytest.mark.django_db
def test_latency_percentiles_computed_from_real_rows():
    org = create_org()
    now = timezone.now()
    for latency in [100, 200, 300, 400, 500]:
        create_request_log(org, latency_ms=latency, created_at=now)

    result = get_latency_percentiles(org, now - timedelta(days=1))

    assert result["sample_count"] == 5
    assert result["p50_ms"] == 300
    assert result["p95_ms"] is not None
    assert result["p99_ms"] is not None


@pytest.mark.django_db
def test_latency_percentiles_with_no_data_returns_none():
    org = create_org()
    now = timezone.now()

    result = get_latency_percentiles(org, now - timedelta(days=1))

    assert result["sample_count"] == 0
    assert result["p50_ms"] is None
    assert result["p95_ms"] is None
    assert result["p99_ms"] is None


@pytest.mark.django_db
def test_queries_only_see_rows_within_time_window():
    org = create_org()
    now = timezone.now()
    create_request_log(org, cost_usd=10.0, created_at=now - timedelta(days=30))
    create_request_log(org, cost_usd=1.0, created_at=now)

    summary = get_spend_summary(org, now - timedelta(days=1))

    assert summary["total_cost_usd"] == 1.0


@pytest.mark.django_db
def test_queries_scope_to_org():
    org_a = create_org(name="A", slug="a")
    org_b = create_org(name="B", slug="b")
    now = timezone.now()
    create_request_log(org_a, cost_usd=10.0, created_at=now)
    create_request_log(org_b, cost_usd=1.0, created_at=now)

    summary = get_spend_summary(org_a, now - timedelta(days=1))

    assert summary["total_cost_usd"] == 10.0
