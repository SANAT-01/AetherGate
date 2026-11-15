# CLAUDE.md — Project Context & Architecture Specification

## 1. Project Overview
**Name:** AetherGate (Multi-Tenant AI FinOps & Smart Routing Gateway)
**Goal:** A lightweight, self-hosted, OpenAI-compatible LLM proxy built for SaaS startups. It reduces API spend via semantic caching, prevents single-provider outages via automatic fallbacks, and enforces real-time per-tenant dollar/token budgets.
**Target Audience:** Startup engineering teams needing a drop-in `base_url` replacement with built-in cost governance and observability.

## 2. Tech Stack & Strict Conventions
* **Backend Framework:** Python 3.12+, Django 5.x, **Django Ninja** (use native `async def` views for the proxy endpoints to handle concurrent I/O without blocking workers).
* **ASGI Server:** Uvicorn / Gunicorn with Uvicorn workers.
* **Database:** PostgreSQL 16+ with the **`pgvector`** extension (`pgvector-python` / `pgvector.django`).
* **Cache & Rate Limiting:** Redis 7+ (`redis.asyncio` for non-blocking proxy checks; atomic **Redis Lua scripts** for budget enforcement).
* **Background Workers:** Celery 5.x with Redis broker (used strictly for post-request telemetry, cost calculation, and embedding storage so the hot proxy path stays <15ms overhead).
* **HTTP Client:** `httpx.AsyncClient` with connection pooling and strict timeouts for upstream LLM calls (OpenAI, Anthropic, Gemini, Ollama).
* **Embeddings (for Semantic Cache):** Fast local model via `fastembed` or `sentence-transformers` (`BAAI/bge-small-en-v1.5`, 384 dimensions) OR lightweight API embeddings so cache lookups don't add high latency or cost.
* **Frontend (Optional Dashboard):** Next.js (App Router) + Tailwind CSS for a 1-page live playground, budget manager, and FinOps cost-savings dashboard.
* **Infrastructure:** Docker & Docker Compose (`web`, `db` with pgvector image `pgvector/pgvector:pg16`, `redis`, `celery_worker`).

## 3. Core Architecture & Hot-Path Request Lifecycle
Every `POST /v1/chat/completions` request must follow this exact pipeline:

1. **Auth & Tenant Resolution:**
   * Extract `Authorization: Bearer <gateway_api_key>` and optional `X-Tenant-ID` header (representing the SaaS startup's end-customer).
   * Look up API key hash and routing/budget config in Redis cache (fallback to Postgres on cache miss).
2. **Pre-Flight FinOps Budget Check (Redis Lua):**
   * Execute an atomic Lua script against Redis checking `tenant:{id}:daily_spend_usd` against `daily_budget_usd`.
   * If exceeded, immediately return `HTTP 429 Too Many Requests` with an OpenAI-formatted error JSON (`insufficient_quota`).
3. **Semantic Cache Lookup (`pgvector`):**
   * Only run if `temperature <= 0.2` and `X-Cache-Control != no-cache` (configurable per route).
   * Embed the normalized user prompt (`384-dim` vector).
   * Query `SemanticCacheEntry` filtered by `organization_id` and `model_group` using Cosine Distance (`<=>`).
   * If `1 - cosine_distance >= similarity_threshold` (default `0.95`), return the cached response immediately (both standard JSON and simulated SSE stream if `stream=True`). Dispatch an async Celery task to log a `CACHE_HIT` with `$0.00` upstream cost and calculated savings.
4. **Smart Routing & Outage Fallback Execution:**
   * Load the organization's `RoutingPolicy` (JSON rules: e.g., primary provider `anthropic/claude-3-5-sonnet`, fallback `openai/gpt-4o-mini`, timeout `5.0s`).
   * Normalize the OpenAI-format payload to the target provider's schema.
   * Attempt primary provider via `httpx.AsyncClient`. On HTTP `429`, `500`, `502`, `503`, `504`, or `httpx.TimeoutException`, automatically retry with the next fallback provider in the chain.
5. **Streaming (SSE) & Non-Blocking Telemetry:**
   * If `stream=True`, yield `data: {...}\n\n` chunks via `StreamingHttpResponse` as they arrive from upstream.
   * Accumulate full completion text and token counts in memory during the stream.
   * Once the stream finishes (`data: [DONE]`), enqueue a Celery task `record_request_telemetry.delay(...)` containing prompt, response, latency, provider used, fallback triggered flag, and token counts.
6. **Post-Flight Spend Reconciliation (Celery Worker):**
   * Calculate exact USD cost using a `ModelPricing` lookup table (`input_tokens * input_price + output_tokens * output_price`).
   * Atomically increment `tenant:{id}:daily_spend_usd` in Redis (`INCRBYFLOAT`) with midnight UTC TTL.
   * Persist `RequestLog` to PostgreSQL and, if cacheable, save the prompt embedding + response into `SemanticCacheEntry`.

## 4. Database Schema (Django Models)
Organize apps cleanly under `apps/`:
* `apps/tenants/`:
  * `Organization`: `id (UUID)`, `name`, `slug`, `created_at`
  * `GatewayAPIKey`: `id`, `org (FK)`, `name`, `key_prefix`, `key_hash`, `is_active`, `routing_policy (FK)`
  * `EndCustomerBudget`: `id`, `org (FK)`, `external_tenant_id (indexed)`, `daily_limit_usd (Decimal)`, `monthly_limit_usd (Decimal)`, `is_blocked`
* `apps/routing/`:
  * `ProviderCredential`: `id`, `org (FK)`, `provider (openai/anthropic/gemini/ollama)`, `encrypted_api_key`
  * `RoutingPolicy`: `id`, `org (FK)`, `name`, `strategy (fallback | cost_optimized | latency)`, `rules_json (JSONField)`, `cache_enabled (bool)`, `similarity_threshold (float)`
  * `ModelPricing`: `model_name (unique)`, `provider`, `input_cost_per_1m_tokens`, `output_cost_per_1m_tokens`
* `apps/gateway/`:
  * `SemanticCacheEntry`: `id`, `org (FK)`, `model_alias`, `prompt_text`, `embedding (VectorField(dimensions=384))`, `response_payload (JSONField)`, `hit_count`, `created_at` (Add HNSW index on `embedding`).
  * `RequestLog`: `id (UUID)`, `org (FK)`, `external_tenant_id`, `api_key (FK)`, `model_requested`, `model_served`, `provider_served`, `status (SUCCESS | CACHE_HIT | FALLBACK_SUCCESS | FAILED | BUDGET_EXCEEDED)`, `prompt_tokens`, `completion_tokens`, `cost_usd`, `saved_usd`, `latency_ms`, `created_at`.

## 5. Folder Structure
```text
aethergate/
├── CLAUDE.md
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── manage.py
├── config/                  # Django settings (base, local, prod), urls, asgi.py, celery.py
├── apps/
│   ├── tenants/             # Orgs, API keys, tenant budgets, Redis Lua budget scripts
│   ├── routing/             # Provider adapters (OpenAI, Anthropic), fallback engine, pricing
│   ├── gateway/             # Django Ninja /v1/chat/completions proxy, pgvector semantic cache
│   └── analytics/           # FinOps aggregation endpoints (spend, cache savings, latency p95)
├── tests/                   # pytest-asyncio tests (mocked upstream LLMs, race conditions, SSE)
└── scripts/                 # Locust load test script & seed_demo_data.py
```

## 6. Implementation & Code Quality Standards
* **Type Hints:** Strict Python type annotations everywhere; validate all incoming/outgoing payloads using Pydantic v2 schemas inside Django Ninja.
* **No Blocking I/O in Async Views:** Never call synchronous Django ORM queries directly inside `async def` proxy routes—use Django's async ORM (`await Model.objects.aget(...)`) or `sync_to_async`.
* **Provider Abstraction:** Implement a clean `BaseLLMProvider` interface (`complete()`, `stream()`) so adding new LLM providers requires zero changes to the router or cache layers.
* **Testing:** Every core feature must have `pytest` coverage using `respx` or `pytest-httpx` to simulate upstream `429` rate limits, timeouts, SSE chunks, and budget cutoffs.
