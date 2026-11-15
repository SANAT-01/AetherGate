# AetherGate

A lightweight, self-hosted, OpenAI-compatible LLM proxy gateway built for SaaS startups. AetherGate reduces API spend via semantic caching, prevents single-provider outages via automatic fallback, and enforces real-time per-tenant dollar budgets. It's a drop-in `base_url` replacement with built-in cost governance and observability — see [claude.md](claude.md) for the full architecture spec.

## Tech stack

Python 3.12, Django 5.x + Django Ninja (async proxy views), PostgreSQL 16 + pgvector (semantic cache), Redis (budgets/rate limiting), httpx (upstream LLM calls), Celery (post-request telemetry, M4+).

## Local setup

```bash
cp .env.example .env   # fill in FREELLMAPI_TOKEN and any other secrets
docker compose up -d db redis
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py createsuperuser
docker compose up web
```

Then via `/admin/`: create an `Organization`, a `GatewayAPIKey` (the raw key is shown once on creation — copy it), and an `EndCustomerBudget` for whichever `external_tenant_id` you'll test with. Tenant provisioning is manual-only; unrecognized `X-Tenant-ID`s are rejected with `403`.

Try it:

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer <raw_key>" -H "X-Tenant-ID: acme-corp" \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Say hello in one word"}]}'
```

Or seed a demo org/key/tenant automatically:

```bash
docker compose run --rm web python scripts/seed_demo_data.py
```

## Tests, lint, types

```bash
pytest                 # or: make test
pytest --cov           # or: make test-cov
ruff check .           # or: make lint
ruff format .          # or: make format
mypy apps config       # or: make typecheck
```

A `Makefile` wraps all of the above plus `make up` / `make down` / `make migrate`. Optional: `pre-commit install` to run ruff automatically on commit (see `.pre-commit-config.yaml`).

## Status

**M1 shipped**: single-provider (FreeLLMAPI) non-streaming passthrough with auth, manual tenant-check, and request logging.

Planned next: M2 budget + rate-limit enforcement → M3 multi-provider fallback → M4 streaming + Celery telemetry → M5 semantic cache → M6 dashboard polish (custom Django admin views, no separate frontend).
