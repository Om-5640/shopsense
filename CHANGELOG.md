# Changelog

All notable changes to ShopSense are documented here.

---

## [Unreleased]

### Changed
- `agents.py`, `rubric.py`, `embeddings.py`, `analysis_normalizer.py`, `cache.py`: replaced all operational `print()` calls with `logging.getLogger(__name__)` calls (`_logger.warning` / `_logger.info`); CLI display output in `rubric.py` (`display_rubric`, `edit_weights`) intentionally left as `print()`

### Added
- `ROADMAP.md`: v10 roadmap covering 9 themes — automated test suite, Redis cache, structured error reporting, export/sharing, user auth, LLM evals, multi-region improvements, price tracking, and PWA support

---

## [9.1.0] — 2026-05-26 — Audit & Hardening Pass

### Fixed (B-01 – B-14)
- **B-01** `getProvidersStatus()` called wrong endpoint (`/api/health` → `/api/providers/status`) and read wrong field
- **B-02** `ignoreBuildErrors: true` removed from `next.config.mjs`; build errors are no longer silently swallowed
- **B-03** Deprecated `@app.on_event("startup")` replaced with `asynccontextmanager` lifespan
- **B-04** `embed_batch` partial-success rebuilding loop fixed; index no longer corrupts on provider failure mid-batch
- **B-05** `rubric.py` boolean precedence bug fixed (`and`/`or` chain); rationale keyword matching made case-insensitive
- **B-06** Case-mismatch mention lookup fixed; `mention_results` dict lowercased before lookup
- **B-07** `{**title_counts, **body_counts}` destructuring silently overwrote title counts; fixed with additive merge
- **B-08** Sentiment LLM calls were uncapped; added `MAX_SENTIMENT_CALLS = 50` hard cap per search session
- **B-09** `run_mention_pipeline` called without `base_registry`; pre-seeded registry now ensures all analysis-discovered products are counted even if coreference returns `{}`
- **B-10** Scorer silently dropped all community/v9 fields; `_COMMUNITY_FIELDS` passthrough added to `_build_scored_dict`
- **B-11** Dead `PRODUCTS_PER_BATCH = 4` constant in `scorer.py` removed; only the active value `3` (line 201) remains
- **B-12** Fuzzy 6-char prefix fallback in `pipeline_runner.py` removed; was causing false attribution (e.g. "Boult Z40" absorbing "Boult Z60" mentions)
- **B-13** Postgres CRUD functions missing `conn.rollback()` on exception; dirty connections were returned to pool. Fixed via `_pg_transaction()` context manager across all 17 PG branches
- **B-14** `cleanup_old_sessions` was defined but never called; wired to hourly asyncio background task in lifespan. Also fixed to evict hung `running` sessions older than `max_age_hours × 2`

### Added
- `_pg_transaction()` context manager in `db.py`: commit on success, rollback on exception, always releases connection
- Hourly session cleanup background task in `main.py` lifespan
- `X-Request-ID` response header middleware (echoes caller header or generates 8-char UUID)
- `logging.basicConfig` configured in lifespan: ISO-timestamp + level + logger name + message format
- `CORS_ORIGINS` env var: CORS allowed origins now configurable at deploy time (default: `localhost:3000`)
- `CORS_ORIGINS` and `OPENAI_BASE_URL` documented in `.env.example`

### Changed
- All bare `print()` calls in `api/` replaced with `logging.getLogger` calls
- `web/package.json`: `postcss` devDep bumped to `^8.5.10`; `overrides` (npm) and `pnpm.overrides` (pnpm) added to force `postcss >= 8.5.10` across full dep tree (fixes GHSA-qx2v-qp2m-jg93)
- `README.md`: corrected `npm install` → `pnpm install` in Quick Start

---

## [9.0.0] — 2025-05-26 — Production Hardening

### Added
- **Circuit breaker** (`llm_clients.py`): Rolling 10-call window per provider; trips at 50% failure rate with 60–120s cooldown; auto-resets after cooldown
- **Smart retry** (`_smart_post_with_retry`): Error-type-aware backoff — 429 → 2s/5s/60s-block; 502/503 → circuit trip; 401/403 → `ProviderAuthError` (permanent dead)
- **`ProviderAuthError`**: New exception class; causes permanent session-dead marking to avoid hammering misconfigured providers
- **`/api/providers/status` endpoint**: Returns per-provider `{configured, session_alive, circuit_blocked, circuit_detail}` — powers the Settings page
- **Domain blacklist** (`domain_blacklist.py`): Auto-blacklists domains after 3 consecutive failures or >70% failure rate; persists to JSON between runs
- **Category-aware review site routing** (`review_fetch.py`): 20+ category → site list mappings; different sites for audio vs. home goods vs. fitness equipment
- **Pipeline stage caching** (`api/pipeline_runner.py`): 1-hour TTL cache keyed on `md5(query|category|rubric_weights)`; cached results replay instantly without re-running agents
- **Pipeline timing instrumentation**: Every stage records `elapsed_s`; total pipeline time logged on completion
- **Adaptive thread summarization concurrency**: Starts at 5 workers; drops stagger from 0.5s → 2.5s on 429 detection; auto-recovers after 30s
- **Smart scoring modes** (`scorer.py`): `SCORING_MODE=fast|hybrid|llm` env toggle; `hybrid` is default (LLM top-10 only, 10× fewer LLM calls)
- **Embeddings provider fallback chain** (`embeddings.py`): Gemini → Cohere → HuggingFace → local `sentence-transformers`; SHA256 in-memory cache
- **SWR caching layer** (`web/lib/hooks.ts`): All GET endpoints cached client-side; 30s for live data, 5min for memory/profile
- **Community data on product cards**: `mention_count`, `distinct_recommenders`, `positive_mentions`, `negative_mentions`, `praise`, `complaints`, `representative_quote`, `sources` all surfaced in the UI
- **Complaint confidence badges**: `confirmed` (3+ users), `reported` (2 users), `single` color-coded in the "What people say" panel
- **Representative quote**: Shown inline under product name when available
- **Source chips**: `r/SubredditName`, `wirecutter.com` chips visible on each card
- **Cross-subreddit split warning**: Amber banner when community opinion is genuinely divided
- **Evidence in scoring breakdown**: Each criterion score now shows the LLM's evidence quote

### Changed
- Thread summarizer `MAX_PARALLEL_WORKERS`: 3 → 5
- Thread summarizer submission stagger: 0.8s → 0.5s (adaptive)
- Product card completely redesigned: community signal row always visible, three expandable sections

### Fixed
- Duplicate `batches` variable bug in `scorer.py` after extraction of `_run_parallel_batch_scoring`

---

## [8.0.0] — 2025-05 — Design System Rebuild

### Added
- Full dark design system rebuild: purple accent `#A78BFA`, background `#08080A`
- 47 Radix-backed shadcn/ui components
- Framer Motion physics-based animations; removed `layoutId` (was causing cards to fly off-screen)
- Command palette (`cmdk`) at ⌘K
- Toast notifications (`sonner`)
- `/memory` page: view + delete user signals and product memories
- `/settings` page: provider status cards with real-time health data
- `/history` page: all past searches with resume link
- `/compare` page: side-by-side product grid
- Product card: rank badge, score bar, price + rating, expandable criteria scores, "Why this fits you"

### Changed
- Rubric sidebar: live sliders → instant re-rank via `useDeferredValue`
- Results page: `AnimatePresence` for product reorder animations

---

## [7.0.0] — 2025-04 — Vector Memory + Deep Reddit

### Added
- PRAW deep Reddit fetcher: 200–300+ comments/thread (`USE_PRAW=true`)
- pgvector memory layer: user signals stored with 768-dim embeddings
- Cross-subreddit validation (`cross_validate.py`): detects community bias, use-case divergence
- `CrossSubredditSignal` type: `consistent|split|single_source` with explanation
- `ProductMemory` type: `considered|rejected|purchased|returned` status tracking
- Signal extractor agent: extracts durable preference signals from interview Q&A
- `/api/memory/*` endpoints: full CRUD for signals and product memories
- Docker Compose for local Postgres + pgvector

---

## [6.0.0] — 2025-03 — Web UI Launch

### Added
- Full Next.js web frontend replacing CLI-only workflow
- FastAPI backend with SSE pipeline streaming
- Interactive interview chat UI
- Live re-ranking sliders (zero API calls — pure client-side math)
- Real price fetching from Amazon.in / Flipkart / Amazon.com via Serper
- Prisma ORM + SQLite for search/profile persistence

---

## [5.0.0] — 2025-02 — Parallel Pipeline

### Added
- Parallel thread summarization (`thread_summarizer.py`): one agent per thread
- 5-provider round-robin pool for thread_summarizer
- OpenRouter as master fallback provider
- Analysis normalizer for defensive JSON coercion
- Authority-tier source weighting (TRUSTED/GOOD/UNKNOWN)

---

## [4.0.0] — 2025-01 — Multi-Provider Agents

### Added
- Agent registry (`agents.py`) with per-agent provider + fallback chain
- Groq, Cerebras, Mistral, OpenRouter support alongside Gemini
- Session-level provider dead tracking
- Category detection agent with disambiguation support
- Budget feasibility filtering (ignores out-of-budget products)

---

## [3.0.0] — 2024-12 — Interview + Rubric

### Added
- Adaptive interview system (4–8 questions, coverage-aware)
- Weighted rubric generation from user profile
- Per-criterion LLM scoring with evidence quotes
- CLI checkpoints: review rubric before research, tweak weights after

---

## [1.0.0] — 2024-11 — Initial Release

### Added
- Reddit thread fetcher with query variations
- Review site scraper (BeautifulSoup)
- Gemini analysis extracting products and complaints
- CLI output with ranked product list
