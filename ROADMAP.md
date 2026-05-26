# ShopSense v10 Roadmap

This document captures the planned direction for v10. Items are grouped by theme, roughly ordered by impact vs. effort.

---

## Theme 1 — Automated Test Suite

**Why now:** CONTRIBUTING.md currently says "there is no automated test suite." The v9.1 audit fixed 14 bugs that were only caught by manual inspection. A test harness would catch regressions automatically.

### Planned work
- `tests/unit/test_analysis_normalizer.py` — property-based tests for every edge case in `normalize_analysis()` (LLM-shape variants, empty inputs, rescued products)
- `tests/unit/test_mention_counter.py` — Aho-Corasick automaton builds, alias resolution, count correctness
- `tests/unit/test_scorer.py` — scoring math, `_COMMUNITY_FIELDS` passthrough, hybrid vs. llm mode
- `tests/unit/test_rubric.py` — weight generation, gap-fill logic, boolean precedence (was B-05)
- `tests/integration/test_db.py` — SQLite and PG paths via `_pg_transaction()`, rollback on exception
- `tests/integration/test_pipeline_runner.py` — session lifecycle, `cleanup_old_sessions()`, hung-session eviction
- `tests/e2e/test_api.py` — FastAPI TestClient smoke tests for every endpoint
- CI: add `pytest tests/unit` step to `.github/workflows/ci.yml`

---

## Theme 2 — Redis Cache Layer

**Why now:** The current pipeline cache (`api/pipeline_runner.py`) uses an in-process dict — it resets on every server restart and can't be shared across multiple workers.

### Planned work
- Add optional `REDIS_URL` env var; fall back to the current in-process dict when unset
- Move pipeline-result cache to Redis with the same 1-hour TTL
- Move `cleanup_old_sessions` to a Redis-native TTL key so no background task is needed
- Move the domain blacklist JSON (`domain_blacklist.py`) to a Redis hash for atomic updates under concurrency
- Docker Compose: add `redis:7-alpine` service alongside the existing `pgvector` service

---

## Theme 3 — Structured Error Reporting

**Why now:** Provider failures surface as `_logger.warning(...)` lines buried in logs. Users on the web UI have no visibility into why a search is slow or incomplete.

### Planned work
- Add a `pipeline_warnings: list[str]` field to the SSE stream's `done` event
- Surface provider fallbacks (e.g., "Groq quota hit — used Gemini instead") as dismissible amber banners on the results page
- Add a `/api/pipeline/:id/diagnostics` endpoint returning per-stage timing + provider chain used
- Structured log format: emit JSON lines in production (`LOG_FORMAT=json` env var) for log aggregators

---

## Theme 4 — Export & Sharing

**Why now:** Users currently can't save or share results outside the browser.

### Planned work
- **PDF export**: server-side render results page with Playwright (`GET /api/search/:id/pdf`)
- **CSV export**: flat `products.csv` with name, score, price, community signals
- **Shareable links**: signed short URLs (`/s/<token>`) that render a read-only results page without needing auth
- Frontend: add "Export" dropdown to the results page header

---

## Theme 5 — User Authentication

**Why now:** All user data (signals, profiles, search history) is stored per-device with no login. Moving between devices loses everything.

### Planned work
- Add `better-auth` (or NextAuth v5) to the Next.js frontend — email magic-link + Google OAuth
- Migrate `UserSignal` and `ProductMemory` tables to include a `user_id` foreign key
- `/api/memory/*` endpoints: require auth header, scope all reads/writes to the authenticated user
- Keep an anonymous/guest path for first-time users (no sign-in required to search)

---

## Theme 6 — Automated Testing of LLM Outputs (Evals)

**Why now:** LLM output shapes change silently when providers update models. The analysis normalizer's defensive coercion means bugs can hide for weeks.

### Planned work
- `tests/evals/`: golden-file tests that replay recorded LLM outputs through the full pipeline and assert the final scored output matches a known-good snapshot
- Fixtures: capture 10–15 real search outputs (anonymized) as JSON fixtures
- Add `make eval` target; run nightly in CI via a scheduled workflow
- Alert (GitHub issue auto-open) if any golden snapshot score deviates by more than ±5 points

---

## Theme 7 — Multi-Region Improvements

**Why now:** `review_fetch.py` and `price_fetcher.py` have region stubs but the frontend has no region picker — users have to know to set `REGION=US` in `.env`.

### Planned work
- Add a `region` field to the search session (default: `IN`)
- Expose a region selector in the search bar UI (flag emoji + dropdown: 🇮🇳 India / 🇺🇸 US / 🇬🇧 UK / 🇦🇺 AU)
- `price_fetcher.py`: add Amazon.co.uk + Amazon.com.au + Flipkart UK-equivalent retailers
- `review_fetch.py`: add UK/AU tech review sites (Techradar, Which?, Choice)
- `reddit_fetch.py`: region-aware subreddit weighting (r/UKpersonalfinance for UK budget questions)

---

## Theme 8 — Price Tracking & Alerts

**Why now:** Users often want to buy later, not now. ShopSense already fetches prices but discards them after the session.

### Planned work
- Persist fetched prices in a new `PriceSnapshot` table (product name, price, retailer, timestamp, search_id)
- Background job: re-fetch prices for tracked products daily
- Alert mechanism: email via Resend when any tracked product drops below a user-set threshold
- Frontend: "Track this price" button on each product card → triggers alert signup flow

---

## Theme 9 — PWA / Mobile

**Why now:** The interview flow involves back-and-forth Q&A that works well on mobile, but the current web app has no PWA manifest or offline support.

### Planned work
- Add `next-pwa` config: offline shell, cached API responses, add-to-home-screen prompt
- Responsive audit: fix any overflow issues on ≤390px screens
- Bottom navigation bar on mobile (replacing the sidebar that collapses poorly at narrow widths)

---

## Non-Goals for v10

The following are explicitly out of scope to keep v10 focused:

- **Rewriting the LLM client layer** — the circuit-breaker + retry system in `llm_clients.py` is working well; no rewrite until there's a concrete performance problem
- **Switching ORMs** — Prisma + SQLite/PG is sufficient; migrating to Drizzle or SQLAlchemy adds churn with no user-visible benefit
- **Real-time price scraping** — Serper-backed price fetching is adequate for now; building a scraper fleet would require significant infrastructure
- **Monetization / billing layer** — out of scope for open-source release

---

## Milestone Summary

| Milestone | Themes | Target |
|-----------|--------|--------|
| v10.0 | Theme 1 (tests), Theme 2 (Redis), Theme 3 (error reporting) | Core reliability |
| v10.1 | Theme 4 (export), Theme 5 (auth) | User value |
| v10.2 | Theme 6 (evals), Theme 7 (multi-region) | Quality + reach |
| v10.3 | Theme 8 (price tracking), Theme 9 (PWA) | Engagement |
