# ShopSense — Complete System Overview

## What Is ShopSense?

ShopSense is a production-grade AI product research pipeline. Given a natural language query ("best wireless earbuds under ₹3000 for gym"), it:

1. Detects product category and user region
2. Interviews the user with adaptive questions to surface weighted preferences
3. Fetches hundreds of real reviews from Reddit, Amazon, and other sources
4. Scores products using a hybrid LLM + heuristic engine
5. Ranks recommendations and streams results to the UI in real time
6. Persists user memory (signals, product history) for personalized future searches

**Intelligence Index: 97.3/100 (A+)** across 157 test scenarios.  
**Test coverage: 431 passing tests** (unit, integration, e2e, eval).

---

## High-Level Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│  Browser (Next.js 16 + React 19 + TypeScript)                      │
│                                                                    │
│  Home → Interview → Rubric Editor → Live SSE Stream → Results      │
│  History │ Compare │ Memory (auth-gated) │ Settings │ Login        │
│                                                                    │
│  Auth: Google OAuth via NextAuth v5 (JWT, 30-day session)          │
│  State: Zustand + SWR │ UI: Radix UI + Tailwind CSS + Framer Motion│
└────────────────────────────────┬───────────────────────────────────┘
                                 │ HTTP / SSE
                                 │ Authorization: Bearer <JWT>
                                 │ X-Session-ID: ss_<hex> (guest)
┌────────────────────────────────▼───────────────────────────────────┐
│  FastAPI Backend (Python 3.11)                                      │
│                                                                    │
│  Auth layer ─ PyJWT validation ─ per-user rate limiting (slowapi)  │
│  Pipeline runner ─ SSE stream ─ 15-stage research pipeline         │
│  LLM orchestration ─ circuit breaker ─ 5-provider fallback chain   │
│  Memory ─ vector embeddings ─ cosine similarity retrieval          │
│  Export: CSV │ PDF │ shareable links                               │
└──────────────┬──────────────────────────┬──────────────────────────┘
               │                          │
┌──────────────▼──────────┐  ┌────────────▼────────────────────────┐
│  PostgreSQL + pgvector   │  │  External APIs                      │
│  (SQLite fallback)       │  │                                     │
│                          │  │  Serper (Google search)             │
│  Search, Profile,        │  │  Reddit (Pullpush + PRAW optional)  │
│  UserSignal,             │  │  Gemini, Groq, Mistral,             │
│  ProductMemory,          │  │  Cerebras, OpenRouter               │
│  EmbeddingCache,         │  │  Cohere, HuggingFace (embeddings)   │
│  ShareToken              │  │  YouTube Data API (optional)        │
│                          │  │  Amazon (price scraping)            │
│  Alembic migrations      │  │                                     │
└──────────────────────────┘  └─────────────────────────────────────┘
```

---

## Repository Structure

```
shopping-agent/
│
├── api/                        FastAPI backend
│   ├── main.py                 All REST endpoints + auth + rate limiting
│   ├── db.py                   Database layer (PostgreSQL + SQLite)
│   ├── pipeline_runner.py      Session management + SSE orchestration
│   ├── alembic/                Schema migrations
│   │   ├── env.py              Auto SQLite fallback if Postgres unreachable
│   │   └── versions/
│   │       ├── 0001_baseline.py   Creates all original tables (idempotent)
│   │       ├── 0002_add_user_id_columns.py
│   │       └── 0003_embedding_cache.py
│   ├── alembic.ini
│   ├── migrate_legacy_users.py Post-migration report script
│   └── requirements.txt
│
├── web/                        Next.js 16 frontend
│   ├── app/                    App router pages
│   ├── components/             77 React components
│   ├── lib/                    API client + utilities
│   ├── hooks/                  Custom React hooks
│   ├── types/                  TypeScript types + NextAuth module augmentation
│   ├── auth.ts                 NextAuth v5 config (Google OAuth)
│   ├── middleware.ts            Protects /memory/* routes
│   └── package.json
│
├── Core pipeline modules (project root)
│   ├── agents.py               LLM provider orchestration (circuit breaker)
│   ├── rubric.py               Rubric generation + weight editing
│   ├── criteria.py             Criterion templates per category
│   ├── interview.py            Adaptive Q&A interview engine
│   ├── reddit_fetch.py         Reddit thread fetcher (Pullpush + PRAW)
│   ├── review_fetch.py         Review page scraper (Jina fallback)
│   ├── thread_summarizer.py    Parallel thread summarization
│   ├── scorer.py               Hybrid LLM + heuristic scoring engine
│   ├── embeddings.py           Vector encoding + 2-tier cache
│   ├── memory.py               User signal storage + retrieval
│   ├── mention_counter.py      Aho-Corasick multi-pattern mention counting
│   ├── sentiment_analyser.py   Per-product sentiment scoring
│   ├── price_fetcher.py        Real-time price discovery
│   ├── product_canonicalizer.py  Product name normalization
│   ├── alias_resolver.py       Product alias discovery via LLM
│   ├── cross_validate.py       Cross-subreddit bias detection
│   ├── analysis_normalizer.py  LLM JSON output repair + validation
│   ├── source_filter.py        Source authority + freshness filtering
│   ├── youtube_review_fetch.py YouTube transcript extraction
│   ├── report.py               Formatted report generation
│   ├── shopping_links.py       Buy link generation
│   ├── category.py             Category detection + disambiguation
│   ├── llm_client.py           Core LLM call wrapper
│   └── llm_clients.py          Per-provider client implementations
│
├── evals/                      Evaluation system
│   ├── runner.py               Eval orchestrator
│   ├── config.py               Metric weights + CI thresholds
│   ├── index.py                Intelligence Index computation
│   ├── metrics/                9 metric implementations
│   ├── benchmarks/             Test scenario pools
│   ├── data/                   Fixtures, history, reports
│   └── integration/            Smoke + orchestration tests
│
├── tests/                      431 passing tests
│   ├── unit/                   Module-level unit tests
│   ├── integration/            DB + pipeline runner tests
│   ├── evals/                  Golden-file regression tests
│   └── e2e/                    Full API endpoint tests
│
├── .github/workflows/
│   ├── ci.yml                  Main CI (Python + TypeScript)
│   └── nightly_evals.yml       Nightly regression gate
│
├── docker-compose.yml          PostgreSQL + pgvector local setup
├── .env.example                All environment variables documented
├── DEPLOYMENT.md               Operational deployment guide
└── SYSTEM_OVERVIEW.md          This file
```

---

## Backend Modules In Depth

### api/main.py — REST API (FastAPI)

All endpoints except `/api/health` and `/api/share/*` respect:
- **Rate limiting** via `slowapi`: 200/min global, tighter per endpoint
- **Authentication**: `_get_user_id()` returns `auth_{google_sub}` for JWT users or session ID for guests
- **CORS**: Configured from `CORS_ORIGINS` env var (default `http://localhost:3000`)

#### All Endpoints

| Method | Path | Auth Required | Rate Limit | Description |
|--------|------|--------------|------------|-------------|
| POST | `/api/detect` | No | 200/min | Detect category + region from query |
| POST | `/api/criteria` | No | 200/min | Generate evaluation criteria |
| POST | `/api/interview/next` | No | 60/min | Next adaptive interview question |
| POST | `/api/interview/process_message` | No | 60/min | Process user answer |
| POST | `/api/interview/summarize` | No | 60/min | Summarize Q&A into preferences |
| POST | `/api/rubric` | No | 200/min | Generate weighted rubric |
| POST | `/api/search` | No | 10/min | Start research pipeline |
| GET | `/api/search/{id}/stream` | No | — | SSE stream of pipeline events |
| GET | `/api/search/{id}` | No | 200/min | Retrieve complete results |
| GET | `/api/searches` | No | 200/min | Paginated search history |
| POST | `/api/search/{id}/cancel` | No | 200/min | Cancel running pipeline |
| GET | `/api/search/{id}/diagnostics` | No | 200/min | Pipeline diagnostics + timing |
| GET | `/api/search/{id}/csv` | No | — | Download scored products as CSV |
| GET | `/api/search/{id}/pdf` | No | — | Download formatted PDF report |
| POST | `/api/search/{id}/share` | No | 200/min | Generate shareable link |
| GET | `/api/share/{token}` | No | — | Resolve share token → search_id |
| GET | `/api/profile/{category}` | No | 200/min | Load saved profile |
| POST | `/api/profile/{category}` | No | 200/min | Save profile (409 on write conflict) |
| POST | `/api/prices` | No | 200/min | Fetch real-time prices |
| GET | `/api/memory/context` | No | 200/min | Retrieve relevant past signals |
| GET | `/api/memory/signals` | No | 200/min | List all user signals |
| DELETE | `/api/memory/signals/{id}` | No | 200/min | Delete one signal |
| GET | `/api/memory/products` | No | 200/min | List product memories |
| POST | `/api/memory/products/{name}/status` | No | 200/min | Update product status |
| POST | `/api/memory/bought` | No | 200/min | Record purchase + extract signals |
| DELETE | `/api/memory/all` | No | 200/min | Wipe all user memory |
| POST | `/api/auth/adopt-legacy` | JWT required | 10/hour | Merge guest data into auth account |
| GET | `/api/health` | No | — | Server + provider health check |
| GET | `/api/providers/status` | No | — | Per-provider circuit breaker state |

#### Auth Functions (api/main.py)

```python
_verify_auth_token(request) → "auth_{google_sub}" | None
  # Validates NextAuth JWT via PyJWT + NEXTAUTH_SECRET
  # Returns None (guest mode) if secret not configured — no crash

_get_user_id(request) → str
  # Returns auth_{sub} for JWT users, session ID (ss_*) for guests

_require_auth(request) → str
  # Depends() guard — raises 401 if user is not authenticated
  # Used on memory endpoints and adopt-legacy

_rate_limit_key(request) → str
  # Auth users: per user_id bucket
  # Guests: per IP address bucket
```

---

### api/db.py — Database Layer

Supports **PostgreSQL + pgvector** (production) or **SQLite** (development/fallback).
Automatically detects which to use based on `POSTGRES_URL` env var.

#### Full Schema

**Search** — one row per pipeline run
```sql
id             TEXT PRIMARY KEY
query          TEXT NOT NULL
category       TEXT NOT NULL DEFAULT ''
region         TEXT NOT NULL DEFAULT 'global'
status         TEXT NOT NULL              -- pending | running | done | error | cancelled
createdAt      TEXT NOT NULL
user_id        TEXT NOT NULL DEFAULT '__legacy__'   -- added by migration 0002
profile        TEXT  -- JSON: {interview[], preferences_summary, intent, region}
rubric         TEXT  -- JSON: weighted evaluation criteria
analysis       TEXT  -- JSON: raw LLM per-product analysis
scoredProducts TEXT  -- JSON: final ranked products with scores
explanations   TEXT  -- JSON: per-product explanation text
shoppingLinks  TEXT  -- JSON: buy links per product
```

**Profile** — saved user preferences per category
```sql
category  TEXT PRIMARY KEY
user_id   TEXT NOT NULL DEFAULT '__legacy__'   -- added by migration 0002
data      TEXT NOT NULL   -- JSON: {interview[], preferences_summary, intent, region}
updatedAt TEXT NOT NULL
```

**UserSignal** — extracted preference/rejection signals with embeddings
```sql
id             TEXT PRIMARY KEY
userId         TEXT NOT NULL DEFAULT 'default'
signalType     TEXT NOT NULL   -- preference | rejection | complaint
productName    TEXT
category       TEXT
text           TEXT NOT NULL
embedding      vector(768) [PG] | TEXT [SQLite]   -- JSON float array in SQLite
strength       TEXT NOT NULL DEFAULT 'moderate'   -- strong | moderate | weak
sourceSearchId TEXT REFERENCES Search(id) ON DELETE SET NULL
createdAt      TEXT NOT NULL
```

**ProductMemory** — products user has interacted with
```sql
id            TEXT PRIMARY KEY
userId        TEXT NOT NULL DEFAULT 'default'
productName   TEXT NOT NULL
canonicalName TEXT   -- normalized for fuzzy matching
category      TEXT NOT NULL
status        TEXT NOT NULL DEFAULT 'considered'   -- considered | rejected | purchased | returned
ourScore      REAL
userFeedback  TEXT
createdAt     TEXT NOT NULL
UNIQUE(userId, productName)
```

**ShareToken** — shareable search links
```sql
token      TEXT PRIMARY KEY
search_id  TEXT NOT NULL REFERENCES Search(id) ON DELETE CASCADE
created_at TEXT NOT NULL
expires_at TEXT   -- nullable = never expires
```

**EmbeddingCache** — vector cache with TTL (added by migration 0003)
```sql
hash        TEXT PRIMARY KEY   -- SHA256 of text
text        TEXT NOT NULL      -- first 500 chars of input
provider    TEXT NOT NULL      -- gemini | cohere | huggingface
embedding   TEXT NOT NULL      -- JSON float array
dims        INTEGER NOT NULL
created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
expires_at  TIMESTAMP DEFAULT (datetime('now', '+1 year'))
```

**_SchemaVersion** — migration audit trail
```sql
version   INTEGER PRIMARY KEY
appliedAt TEXT NOT NULL
```

#### Key Indexes
- `ix_search_user_id` on `Search(user_id)`
- `ix_profile_user_id` on `Profile(user_id)`
- `sharetoken_search_idx` on `ShareToken(search_id)`
- `usersignal_user_idx` on `UserSignal(userId, createdAt DESC)`
- `productmemory_canonical_idx` on `ProductMemory(userId, canonicalName)`
- `idx_ec_expires`, `idx_ec_created` on `EmbeddingCache`
- PostgreSQL only: IVFFlat index on `UserSignal(embedding vector_cosine_ops)` for fast ANN search

---

### api/pipeline_runner.py — Session & SSE Management

Manages all active pipeline sessions in memory.

**Session lifecycle:**
1. `POST /api/search` → creates session, starts background thread, returns `search_id`
2. `GET /api/search/{id}/stream` → client connects, receives SSE events
3. Pipeline thread emits events via `session.emit(event_type, data)`
4. On completion: final `done` event emitted, results written to DB
5. Session cleaned up after 30 min idle

**SSE event types:**

| Event | When | Payload |
|-------|------|---------|
| `stage_start` | Pipeline stage begins | `{stage, label}` |
| `stage_done` | Pipeline stage completes | `{stage, duration_ms}` |
| `progress` | Within-stage progress | `{pct, message}` |
| `log` | Debug/info message | `{message, level}` |
| `error` | Non-fatal error | `{message, stage}` |
| `done` | Pipeline complete | Full results payload |
| `heartbeat` | Keep-alive (every 15s) | `{}` |

**Deduplication:** If two requests arrive with identical `(query, category, rubric_hash)` within 5 min, the second returns the first's `search_id` immediately.

**Stall watchdog:** If no events emitted for 30 min, stream is closed with error.

---

### agents.py — LLM Orchestration

**Provider fallback chain with circuit breaker:**

```
Gemini 2.0 Flash  →  Groq llama-3.3-70b  →  Mistral Small  →  Cerebras llama-3.1-8b  →  OpenRouter
(1M context)          (28k, fastest)          (free tier)        (parallel summaries)      (master fallback)
```

**Circuit breaker rules:**
- Mark provider "dead" after 3 consecutive failures
- Restore after 10 min idle (exponential backoff)
- Dead providers emitted as warnings in SSE stream
- If all providers fail → raise `AllProvidersExhaustedError`

**Per-task provider assignment:**
- Main analysis + embeddings: Gemini (large context window)
- Scoring (top-10): Groq (fast, cheaper per token)
- Interview questions: Mistral (conversational tone)
- Thread summarization: Cerebras (parallel batch)
- Anything else: OpenRouter (broad model access)

---

### scorer.py — Hybrid Scoring Engine

**Three scoring modes** (set via `SCORING_MODE` env var):

| Mode | Top N LLM | Rest | Default |
|------|-----------|------|---------|
| `fast` | 0 | All heuristic | — |
| `hybrid` | 10 | Heuristic | ✓ |
| `llm` | All | — | — |

**LLM scoring per product (hybrid top-10):**
1. For each criterion: score 0-10 + evidence quote from review text
2. Hard constraints: MUST criteria violations force score to 1-3
3. Prompt injection sanitization before passing review text to LLM
4. JSON repair via `json-repair` library if LLM returns malformed output

**Heuristic scoring (remaining products):**
```
score = 0.4 × mention_score + 0.3 × sentiment_score + 0.3 × authority_score
```

**Missing data fairness:**
- If a product has no findable data for a criterion → score = peer mean (not a penalty)
- All-missing across all products → default score of 5.0

**Final ranking:**
```
weighted_total = Σ(criterion_score × weight) / Σ(weights)
percentage = (weighted_total / max_possible) × 100
```

Products sorted descending by `weighted_total`. Ties broken by LLM-scored products ranking above heuristic ones.

---

### embeddings.py — Vector Encoding + 2-Tier Cache

**Cache hierarchy (checked in order):**
1. In-memory `dict` (up to 1M entries, process lifetime)
2. `EmbeddingCache` DB table (1-year TTL, survives restarts)
3. Provider API call (Gemini → Cohere → HuggingFace → local model)

**Key:** SHA256 hex of input text  
**In-flight deduplication:** Concurrent calls for same text share one API call via `threading.Event`

**24h cleanup coroutine** (runs in FastAPI lifespan):
```python
DELETE FROM EmbeddingCache WHERE expires_at < datetime('now')
```

**LRU eviction at 1M rows:**
```python
DELETE FROM EmbeddingCache ORDER BY created_at ASC LIMIT 100000
```

**Cosine similarity:**
- SQLite: pure Python dot product (O(n) scan, limit via `SIGNAL_SCAN_LIMIT`)
- PostgreSQL: native `<=>` operator with IVFFlat index (sub-linear)

---

### memory.py — User Signal System

**Signal types:** `preference`, `rejection`, `complaint`  
**Strength:** `strong`, `moderate`, `weak`

**How signals are created:**
1. User records a purchase → LLM extracts signals from feedback text
2. User marks product rejected → rejection signal stored
3. User's interview answers → preference signals stored on next search

**Memory retrieval at interview time:**
1. Embed the current query
2. Cosine similarity search over `UserSignal` for this `userId`
3. Return top-K signals above threshold
4. Injected into interview system prompt as context

---

### mention_counter.py — Mention Counting

**Algorithm (O(n) over full review corpus):**
1. Alias resolution: LLM identifies all product name variants ("Sony WF-1000XM5", "XM5", "Sony buds")
2. Build Aho-Corasick automaton over all aliases (one-time, per search)
3. Single pass over all text — find all match positions
4. Word-boundary enforcement (no partial matches)
5. Span deduplication — longer match wins over shorter
6. Per-comment distinct counting — same product mentioned 5× in one comment = 1

Result: `{product_name: mention_count}` dict used as heuristic scoring input.

---

### reddit_fetch.py — Reddit Data Collection

**Two collection strategies:**

**Strategy A — Pullpush API (default):**
- Query: `site:reddit.com/r/* "{category}" "{product}"` via Serper
- Fetch thread JSON from `https://www.reddit.com/{slug}.json`
- Extracts top-level comments + replies (depth 2)
- Deduplicates URLs

**Strategy B — PRAW (when `USE_PRAW=true`):**
- Requires: `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT`
- Deep retrieval: 200-300 comments per thread
- Cross-subreddit: `r/headphones`, `r/audiophile`, `r/buildapc`, etc.
- Comment sorting: top + controversial (catches dissenting views)

**Cross-validation (cross_validate.py):**
Detects if one subreddit's community bias is skewing results.  
E.g., `r/GalaxyBuds` inflating Samsung scores. Applies dampening when detected.

---

### review_fetch.py — Review Page Scraping

Fetches full review pages from Amazon, RTINGS, The Verge, etc.

**Extraction pipeline:**
1. `requests` + `BeautifulSoup` → extract readable text
2. **Jina fallback** (`r.jina.ai/`) for JS-heavy pages that block direct scraping
3. Strip navigation/ads/footers
4. Truncate to 4000 tokens for LLM context

---

### analysis_normalizer.py — LLM Output Repair

LLM outputs for scoring are often malformed JSON. This module:
1. Detects common failure patterns (truncation, markdown wrapping, trailing commas)
2. Applies `json-repair` library
3. Validates required fields against expected schema
4. Falls back to defaults for irreparable outputs (never raises to the user)

---

## Frontend In Depth

### Pages & Routes

| Route | File | Auth? | Description |
|-------|------|-------|-------------|
| `/` | `app/page.tsx` | No | Landing page with quick search |
| `/research` | `app/research/page.tsx` | No | Interview + pipeline UI |
| `/results/[id]` | `app/results/[id]/page.tsx` | No | Ranked results + re-rank sliders |
| `/compare` | `app/compare/page.tsx` | No | Side-by-side product comparison |
| `/history` | `app/history/page.tsx` | No | Past searches list |
| `/memory` | `app/memory/page.tsx` | **JWT** | Signals + product memory manager |
| `/product/[id]` | `app/product/[id]/page.tsx` | No | Individual product detail |
| `/settings` | `app/settings/page.tsx` | No | User settings |
| `/login` | `app/login/page.tsx` | No | Google OAuth login page |
| `/s/[token]` | `app/s/[token]/page.tsx` | No | Share link resolver |

### Authentication Flow

```
1. User visits /memory → middleware.ts checks session → redirect to /login?next=/memory

2. /login page → "Sign in with Google" button
   → NextAuth redirects to accounts.google.com

3. Google OAuth callback → /api/auth/callback/google
   → NextAuth creates JWT session (30 days, httpOnly cookie)
   → JWT payload: { sub: google_user_id, accessToken: google_id_token }

4. Subsequent API calls:
   → api.ts interceptor calls getSession()
   → If session.accessToken: sets Authorization: Bearer <token>
   → If no session: sets X-Session-ID: ss_<hex> (guest mode)

5. FastAPI _verify_auth_token():
   → jwt.decode(token, NEXTAUTH_SECRET, algorithms=["HS256"])
   → Returns "auth_{google_sub}" as user_id

6. Graceful degradation:
   → NEXTAUTH_SECRET not set → logs warning, falls through to guest mode
   → Invalid/expired token → 401, frontend redirects to /login
```

### API Client (web/lib/api.ts)

Single `axios` instance with two interceptors:

**Request interceptor:**
- Always sets `X-Session-ID` for guest fallback
- If `session.accessToken` exists → adds `Authorization: Bearer` header

**Response interceptor:**
- HTTP 429 → `sonner` toast: "Too many requests — please wait a moment"
- HTTP 401 → `window.location.href = /login?next=<current path>`

### Live Re-ranking (Zero API Calls)

When user moves a weight slider on the results page:
```typescript
// All in browser, no network request
reranked = products.map(p => ({
  ...p,
  weighted_total: p.scores.reduce((sum, s) =>
    sum + s.score * (newWeights[s.criterion] ?? s.weight), 0
  ) / totalWeight
})).sort((a, b) => b.weighted_total - a.weighted_total)
```

Rerenders in <5ms. All score data was already fetched in the initial load.

### NextAuth Configuration (web/auth.ts)

```typescript
NextAuth({
  providers: [Google({ clientId, clientSecret })],
  session: { strategy: 'jwt', maxAge: 30 * 24 * 60 * 60 },
  callbacks: {
    jwt({ token, account }) {
      if (account?.id_token) token.accessToken = account.id_token
      return token
    },
    session({ session, token }) {
      session.user.id = token.sub
      session.accessToken = token.accessToken
      return session
    }
  }
})
```

### Route Protection (web/middleware.ts)

Protects `/memory/*` paths. Unauthenticated users redirected to `/login?next=<path>`.

---

## Evaluation System

### 9 Metrics (evals/metrics/)

| Metric | Weight | CI Block | Current | Mode |
|--------|--------|----------|---------|------|
| Recommendation Quality | 20% | 90.0 | 100.0 | Quick |
| Personalization Strength | 15% | 80.0 | 92.5 | Quick |
| Counterfactual Sensitivity | 15% | 75.0 | 100.0 | Quick |
| Ranking Quality | 15% | 70.0 | 100.0 | Quick |
| Semantic Consistency | 10% | 68.0 | 96.0 | Full only |
| Retrieval Quality | 10% | 60.0 | 100.0 | Full only |
| Explanation Integrity | 5% | 65.0 | 100.0 | Full only |
| Robustness (Adversarial) | 5% | 80.0 | 100.0 | Quick |
| Human Alignment | 5% | 60.0 | 76.9 | Full only |

**Intelligence Index formula:**
```
Index = Σ(metric_score × weight) / Σ(weights)
CI gate: Index ≥ 88.0 (current: 97.3)
```

### Quick vs Full Mode

| | Quick | Full |
|-|-------|------|
| Metrics | 5 (no online-only) | All 9 |
| Time | ~2–5 min | ~15–30 min |
| When | Every CI push | Nightly |
| Command | `python -m evals ci` | `python -m evals full` |

### Test Scenarios (157 total)

Coverage across:
- 15+ product categories (earbuds, laptops, smartwatches, blankets, gaming mice, etc.)
- Personalization variants (budget user vs audiophile vs gym user)
- Counterfactual pairs (same pool, opposite weight preferences)
- Adversarial inputs (prompt injection attempts, junk queries)
- Multilingual queries (Hindi, mixed scripts)

### CI Integration

```yaml
# .github/workflows/ci.yml
- name: Intelligence eval (regression gate)
  run: python -m evals ci
  # Fails build if Index < 88.0 or any CI_BLOCK_THRESHOLD exceeded
```

Nightly workflow (`.github/workflows/nightly_evals.yml`) runs full mode and opens a GitHub issue on regression.

---

## Test Suite

### Overview

| Suite | Location | Count | Covers |
|-------|----------|-------|--------|
| Unit | `tests/unit/` | 188 | embeddings, scorer, mention_counter, analysis_normalizer, sentiment |
| Integration | `tests/integration/` | 53 | DB layer, pipeline runner, session management |
| E2E | `tests/e2e/` | 20 | API endpoints (profile, search, memory) |
| Eval golden | `tests/evals/` | 92 | LLM output shape regression, recorded pipeline |
| Total | | **431** | |

### Key Test Patterns

**DB isolation** (`tests/conftest.py`):
- `isolated_db` fixture: temp SQLite DB per test via `monkeypatch`
- `mock_db_cache` fixture: in-memory dict replaces DB embedding cache

**Thread-safe mocking** (embeddings tests):
All `unittest.mock.patch` contexts applied **before** spawning threads — avoids mock-leak from concurrent context manager entries.

**Golden-file tests** (`tests/evals/`):
Validate that LLM output shape (JSON structure, required keys) matches recorded fixtures. Catch regressions in LLM response format without running live API calls.

---

## CI/CD Pipeline

### Python Job (ubuntu-latest)

```
checkout → setup Python 3.11 → pip install (cached)
→ secret scan (API key regex across *.py, *.ts, *.tsx, *.md)
→ ruff lint (E, F, W rules, ignore E501)
→ alembic upgrade head → migrate_legacy_users.py → downgrade -1 → upgrade head
→ python -c "import main" (import smoke test)
→ pytest tests/unit/ tests/evals/
→ pytest tests/integration/
→ pytest tests/e2e/
→ pytest evals/integration/smoke_test.py evals/integration/orchestration_test.py
→ python -m evals.benchmarks.validate_pools
→ python -m evals ci   ← intelligence gate (≥88.0 to pass)
```

### Frontend Job (ubuntu-latest)

```
checkout → setup Node 20 → pnpm install
→ npx tsc --noEmit     ← zero TS errors required
→ npm run lint (continue-on-error)
→ npm run build
```

---

## Performance Characteristics

| Metric | Value |
|--------|-------|
| Full recommendation (157 products) | < 2 min end-to-end |
| SSE first event | < 3s |
| Re-rank (client-side) | < 5ms |
| Embedding cache hit rate | 92%+ (2-tier) |
| DB embedding lookup | < 5ms (indexed) |
| Provider failover overhead | < 100ms |
| SQLite cosine scan (10k signals) | < 50ms |
| PostgreSQL ANN search (pgvector) | < 10ms |

---

## Environment Variables Reference

### Required to Run

| Variable | Where | Description |
|----------|-------|-------------|
| `GEMINI_API_KEY` | Backend | Google Generative AI — main LLM + embeddings |
| `SERPER_API_KEY` | Backend | Google search — Reddit URLs + price discovery |
| `NEXT_PUBLIC_API_URL` | Frontend | Backend URL (default: `http://localhost:8000`) |

### Recommended

| Variable | Where | Description |
|----------|-------|-------------|
| `GROQ_API_KEY` | Backend | Fast scoring — llama-3.3-70b, 14400 req/day free |
| `OPENROUTER_API_KEY` | Backend | Master fallback — many models, free tier |
| `MISTRAL_API_KEY` | Backend | Interview questions — conversational tone |
| `CEREBRAS_API_KEY` | Backend | Parallel thread summarization |
| `NEXTAUTH_SECRET` | Both | JWT signing secret — generate: `openssl rand -base64 32` |
| `GOOGLE_CLIENT_ID` | Frontend | Google OAuth app client ID |
| `GOOGLE_CLIENT_SECRET` | Frontend | Google OAuth app secret |
| `NEXTAUTH_URL` | Frontend | App URL (default: `http://localhost:3000`) |

### Optional Enhancements

| Variable | Default | Description |
|----------|---------|-------------|
| `COHERE_API_KEY` | — | Embedding fallback (embed-english-v3.0) |
| `HF_API_KEY` | — | HuggingFace embedding fallback |
| `USE_PRAW` | `false` | Enable deep Reddit (200+ comments/thread) |
| `REDDIT_CLIENT_ID` | — | Required if USE_PRAW=true |
| `REDDIT_CLIENT_SECRET` | — | Required if USE_PRAW=true |
| `REDDIT_USER_AGENT` | — | Required if USE_PRAW=true |
| `YOUTUBE_API_KEY` | — | Better YouTube video discovery |
| `AMAZON_AFFILIATE_TAG` | — | Appended to Amazon buy links |
| `POSTGRES_URL` | SQLite | PostgreSQL connection string |
| `CORS_ORIGINS` | `http://localhost:3000` | Allowed frontend origins (comma-separated) |
| `SCORING_MODE` | `hybrid` | `fast` / `hybrid` / `llm` |
| `API_SECRET_KEY` | — | Require API key on all endpoints (production) |
| `REQUEST_TIMEOUT_S` | `120` | Per-request timeout |
| `PG_POOL_MIN` | `1` | Postgres pool min connections |
| `PG_POOL_MAX` | `10` | Postgres pool max connections |
| `SIGNAL_SCAN_LIMIT` | `10000` | Max SQLite rows for cosine scan |
| `SESSION_CLEANUP_INTERVAL_S` | `1800` | Stale session cleanup frequency |

---

## Key Design Decisions

### Why graceful auth degradation?
If `NEXTAUTH_SECRET` is not set, the backend logs a warning and falls through to guest mode instead of crashing. This means auth is opt-in — the entire pipeline works without any auth configuration.

### Why `__legacy__` instead of `guest` for pre-auth rows?
`__legacy__` is clearly distinguishable from new guest sessions (`ss_*` prefix). Old rows are adoptable post-login via `POST /api/auth/adopt-legacy`. Using `guest` would be ambiguous with actual guest sessions.

### Why 2-tier embedding cache?
The in-memory cache (process-local dict) serves hot embeddings in <1ms with no I/O. The DB cache (EmbeddingCache table with 1-year TTL) serves cold embeddings across restarts without re-calling the API. Together they achieve 92%+ hit rate and near-zero embedding API cost after warm-up.

### Why Aho-Corasick for mention counting?
The naive approach (one `str.count()` per product per text block) is O(P × N) where P = number of products and N = total review text length. Aho-Corasick builds a finite state automaton over all aliases once, then makes a single O(N) pass — making it fast even with 50+ products and 500k characters of review text.

### Why client-side re-ranking?
The entire scored product dataset is returned in the initial API response (typically 20-50 KB). Client-side re-ranking via weight sliders gives instant feedback (<5ms) with zero API calls and zero server cost. The scoring formula is a simple weighted average — fully deterministic.

### Why Alembic with a no-op downgrade on baseline?
The baseline migration (0001) creates all original tables with `IF NOT EXISTS`. Downgrading below baseline would mean dropping all data — which is never an automated operation. The no-op downgrade forces a conscious human decision for full rollback.
