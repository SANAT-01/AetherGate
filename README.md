# AetherGate

A lightweight, self-hosted, OpenAI-compatible LLM proxy gateway built for SaaS startups. AetherGate reduces API spend via semantic caching, prevents single-provider outages via automatic fallback, and enforces real-time per-tenant dollar budgets. It's a drop-in `base_url` replacement with built-in cost governance and observability — see [claude.md](claude.md) for the full architecture spec.

## Tech stack

Python 3.12, Django 5.x + Django Ninja (async proxy views), PostgreSQL 16 + pgvector (semantic cache), Redis (budgets/rate limiting + Celery broker), httpx (upstream LLM calls), Celery (post-request telemetry, offloaded to a dedicated `celery_worker` container).

## High-level design

### Components

```mermaid
flowchart TB
    Client["Client App<br/>(any OpenAI SDK / curl / Postman)"]

    subgraph gw["AetherGate web (Django + Ninja, async)"]
        Router["POST /v1/chat/completions<br/>apps/gateway/api.py"]
        Auth["Auth + tenant resolution<br/>apps/gateway/auth.py"]
        RateLimit["Rate limiter (Lua)<br/>apps/gateway/rate_limit.py"]
        Budget["Budget check + spend record (Lua)<br/>apps/gateway/budget.py"]
        Engine["Fallback engine<br/>apps/routing/engine.py<br/>(complete + stream)"]
        Provider["Provider adapters<br/>apps/routing/providers/*"]
        SSE["SSE generator<br/>_sse_response_generator"]
        Cache["Semantic cache lookup<br/>(pgvector) — planned M5"]
        Admin["Django Admin<br/>/admin/ — manual tenant & key provisioning"]
    end

    subgraph worker["celery_worker (separate container, same codebase)"]
        Task["record_request_telemetry<br/>apps/gateway/tasks.py"]
    end

    Postgres[("PostgreSQL + pgvector<br/>Organization, GatewayAPIKey,<br/>EndCustomerBudget, RequestLog,<br/>ModelPricing, SemanticCacheEntry")]
    Redis[("Redis<br/>ratelimit:* counters<br/>tenant:*:daily_spend_usd<br/>+ celery broker queue")]
    LLM["Upstream LLM providers<br/>FreeLLMAPI + OpenAI,<br/>fallback chain via RoutingPolicy"]

    Client -->|"Bearer key + X-Tenant-ID"| Router
    Router --> Auth
    Auth <-->|lookup key / tenant| Postgres
    Router --> RateLimit
    RateLimit <-->|INCR + EXPIRE| Redis
    Router --> Budget
    Budget <-->|GET / INCRBYFLOAT| Redis
    Router -.->|cache hit?| Cache
    Cache <-.->|cosine search| Postgres
    Router --> Engine
    Engine --> Provider
    Provider -->|HTTPS, incl. SSE streaming| LLM
    Engine --> SSE
    SSE -->|"data: ...chunks / [DONE]"| Client
    Router -->|"await _enqueue_telemetry(...)<br/>(sync_to_async .delay())"| Redis
    Redis -->|"BRPOP (blocking)"| Task
    Task -->|RequestLog.objects.create| Postgres
    Admin <-->|CRUD| Postgres

    style Cache stroke-dasharray: 5 5
```

### Request flow — `POST /v1/chat/completions`

```mermaid
sequenceDiagram
    participant C as Client
    participant G as Gateway (api.py)
    participant PG as Postgres
    participant R as Redis
    participant P as Provider (FreeLLMAPI/OpenAI)
    participant W as celery_worker

    C->>G: POST /v1/chat/completions<br/>Bearer key, X-Tenant-ID
    G->>R: check_ip_rate_limit (Lua: INCR + EXPIRE, keyed on client IP)
    alt over IP limit (no org known yet, no log written)
        G-->>C: 429 rate_limit_exceeded
    end
    G->>PG: resolve_api_key(raw_key)
    alt invalid/missing key
        G-->>C: 401 invalid_api_key
    end
    G->>PG: resolve_end_customer(org, tenant_id)
    alt unknown/blocked tenant
        PG-->>G: not found
        G-)R: _enqueue_telemetry(FAILED)
        G-->>C: 403 unknown_tenant
    end
    G->>R: check_rate_limit (Lua: INCR + EXPIRE, keyed on api_key.id)
    alt over limit
        G-)R: _enqueue_telemetry(FAILED)
        G-->>C: 429 rate_limit_exceeded
    end
    G->>R: check_budget (Lua: GET vs daily_limit_usd)
    alt over budget
        G-)R: _enqueue_telemetry(BUDGET_EXCEEDED)
        G-->>C: 429 budget_exceeded
    end
    G->>PG: load RoutingPolicy.rules_json (or default single-item chain)

    alt stream = false
        loop for each provider in fallback chain
            G->>P: complete(model, messages)
            alt success
                P-->>G: response + usage (tokens)
            else 429/5xx/timeout (transient)
                P-->>G: error
                Note over G: advance to next provider in chain
            else other error
                P-->>G: error
                G-)R: _enqueue_telemetry(FAILED)
                G-->>C: 502 upstream_error (no fallback)
            end
        end
        alt chain exhausted
            G-)R: _enqueue_telemetry(FAILED)
            G-->>C: 502 upstream_error
        end
        G->>PG: lookup ModelPricing(model_served)
        G->>R: record_spend (Lua: INCRBYFLOAT, EXPIREAT midnight UTC)
        G-)R: _enqueue_telemetry(SUCCESS/FALLBACK_SUCCESS, cost_usd)
        G-->>C: 200 OpenAI-shaped response
    else stream = true
        loop for each provider in fallback chain (only before 1st chunk)
            G->>P: stream(model, messages) — pull first chunk
            alt first chunk OK
                Note over G: commit to this provider, start SSE response
            else 429/5xx/timeout (transient)
                Note over G: advance to next provider in chain
            end
        end
        alt chain exhausted before any first chunk
            G-)R: _enqueue_telemetry(FAILED)
            G-->>C: 502 upstream_error
        end
        loop per upstream SSE chunk
            P-->>G: data: {...delta...}
            G-->>C: data: {chat.completion.chunk}
        end
        P-->>G: trailing chunk: empty choices + usage{prompt/completion_tokens}
        alt mid-stream failure (malformed chunk / transport error)
            G-)R: _enqueue_telemetry(FAILED)
            Note over G,C: stream ends early, no [DONE]
        else normal completion
            G->>PG: lookup ModelPricing(model_served)
            G->>R: record_spend (Lua: INCRBYFLOAT)
            G-)R: _enqueue_telemetry(SUCCESS/FALLBACK_SUCCESS, cost_usd)
            G-->>C: data: [DONE]
        end
    end

    R->>W: BRPOP celery (blocking pop, fires on enqueue)
    W->>PG: RequestLog.objects.create(...)
```

**Legend:** `-)` = fire-and-forget async enqueue (`await _enqueue_telemetry(...)`, a `sync_to_async`-wrapped `.delay()`) — the gateway never waits on the resulting Postgres write; a separate `celery_worker` container dequeues and performs it. Dashed boxes = planned, not yet implemented (semantic cache → M5). Everything else above is shipped (M1 + M2 + M2.5 + M3 + M4).

## Local setup

```bash
cp .env.example .env   # fill in FREELLMAPI_TOKEN and any other secrets
docker compose up -d db redis
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py createsuperuser
docker compose up web celery_worker
```

`celery_worker` runs the same image as `web` (just a different command) and consumes `RequestLog` telemetry tasks off Redis — without it running, requests still succeed, but telemetry rows simply queue up unprocessed until a worker is started.

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

### Inspecting the data stores

- **pgAdmin** (Postgres UI): `docker compose up -d pgadmin` → `http://localhost:5050`
- **RedisInsight** (Redis UI): `docker compose up -d redisinsight` → `http://localhost:5540`. Useful for inspecting live budget (`tenant:*:daily_spend_usd`) and rate-limit (`ratelimit:*`) keys, and the `celery` list key (Celery's default queue) — its length should stay near 0 while `celery_worker` is running and healthy.

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

**M2 shipped**: atomic Redis-backed daily budget enforcement and per-API-key rate limiting, both pre-flight (before any upstream call).

**M2.5 shipped**: pre-auth, IP-based rate limiting — a second, independent limiter (`IP_RATE_LIMIT_PER_MINUTE`, default 300/min) that runs before the Postgres auth lookup, protecting the server from unauthenticated/invalid-key request floods. The per-API-key limiter from M2 still runs separately afterward for authenticated abuse.

**M3 shipped**: multi-provider fallback. `RoutingPolicy.rules_json` defines a per-org fallback chain (up to 3 attempts: primary + 2 fallbacks); on a transient upstream failure (429/5xx/timeout) the gateway advances to the next provider automatically. `ProviderCredential.encrypted_api_key` is now real (Fernet-encrypted, admin-managed), and a second provider (`OpenAIProvider`) proves the mechanism end-to-end. Orgs with no `RoutingPolicy` configured see unchanged M1/M2 behavior — a single provider attempt.

**M4 shipped** (streaming + Celery-offloaded telemetry): `stream=True` requests are served as real Server-Sent Events end-to-end. The same fallback chain from M3 applies, but only up to the first streamed chunk — once a provider starts sending content the HTTP status is committed, so a later disconnect just ends the response early rather than retrying. Token/cost accounting for streamed responses is now captured from the upstream's trailing usage chunk (an empty-`choices` SSE event carrying a `usage` object), so `prompt_tokens`/`completion_tokens`/`cost_usd` are populated the same as non-streaming requests. Every `RequestLog` write (success, failure, budget-exceeded, rate-limited) is now offloaded to a Celery task (`apps/gateway/tasks.py::record_request_telemetry`), dispatched via `await _enqueue_telemetry(...)` so the hot request path never blocks on the Postgres insert; a dedicated `celery_worker` container (same image as `web`, reusing Redis as the broker) consumes and persists them.

**M6 shipped**: FinOps aggregation endpoints + admin dashboard. New `apps/analytics/` app exposes `GET /v1/analytics/{spend,cache-savings,latency}` (Bearer-key auth, same convention as the proxy endpoint; scoped to the caller's own org, `?days=N` window, default 7), plus a lightweight dashboard bolted onto the existing Django admin at `/admin/gateway/requestlog/dashboard/` (linked from the `RequestLog` changelist) that renders the same aggregates as plain HTML tables — no new frontend or charting dependency. Cache-savings numbers report cleanly as zero until semantic caching (M5) actually produces `CACHE_HIT` rows.

Planned next: M5 semantic cache.
