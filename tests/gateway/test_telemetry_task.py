import pytest

from apps.gateway.models import RequestLog
from apps.gateway.tasks import record_request_telemetry
from tests.factories import create_org


@pytest.mark.django_db
def test_record_request_telemetry_persists_all_fields():
    org = create_org()

    record_request_telemetry(
        org_id=org.id,
        external_tenant_id="acme-corp",
        api_key_id=None,
        model_requested="auto",
        model_served="qwen/qwen3.8-27b",
        provider_served="freellmapi",
        status=RequestLog.Status.SUCCESS,
        prompt_tokens=10,
        completion_tokens=5,
        cost_usd="0.000123",
        latency_ms=42,
    )

    log = RequestLog.objects.get(org=org)
    assert log.external_tenant_id == "acme-corp"
    assert log.model_served == "qwen/qwen3.8-27b"
    assert log.status == RequestLog.Status.SUCCESS
    assert log.prompt_tokens == 10
    assert log.completion_tokens == 5
    assert str(log.cost_usd) == "0.000123"
    assert log.latency_ms == 42


@pytest.mark.django_db
def test_record_request_telemetry_handles_no_cost():
    org = create_org()

    record_request_telemetry(
        org_id=org.id,
        external_tenant_id="acme-corp",
        api_key_id=None,
        model_requested="auto",
        status=RequestLog.Status.FAILED,
        latency_ms=5,
    )

    log = RequestLog.objects.get(org=org)
    assert log.status == RequestLog.Status.FAILED
    assert log.cost_usd is None
    assert log.model_served == ""
