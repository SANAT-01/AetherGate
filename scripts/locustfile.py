"""Minimal Locust load test for POST /v1/chat/completions.

This is a starting point, not a tuned load profile — adjust wait_time,
payload, and concurrency to match a real capacity test.

Usage:
    GATEWAY_API_KEY=<raw_key> GATEWAY_TENANT_ID=<tenant_id> \\
        locust -f scripts/locustfile.py --host http://localhost:8000
"""

import os

from locust import HttpUser, between, task

API_KEY = os.environ.get("GATEWAY_API_KEY", "changeme")
TENANT_ID = os.environ.get("GATEWAY_TENANT_ID", "demo-tenant")


class GatewayUser(HttpUser):
    wait_time = between(1, 3)

    @task
    def chat_completion(self) -> None:
        self.client.post(
            "/v1/chat/completions",
            json={
                "model": "auto",
                "messages": [{"role": "user", "content": "Say hello in one word"}],
            },
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "X-Tenant-ID": TENANT_ID,
                "Content-Type": "application/json",
            },
        )
