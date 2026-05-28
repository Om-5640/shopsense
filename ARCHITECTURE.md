# Architecture — ShopSense

Deep technical reference. For a high-level overview see [README.md](README.md).

---

## Table of Contents

1. [Full Pipeline Flow](#1-full-pipeline-flow)
2. [Structured User Intent Model](#2-structured-user-intent-model)
3. [Agent Registry](#3-agent-registry)
4. [LLM Provider Failover](#4-llm-provider-failover)
5. [Memory Layer](#5-memory-layer)
6. [Scoring Algorithm](#6-scoring-algorithm)
7. [Database Schema](#7-database-schema)
8. [API Endpoint Reference](#8-api-endpoint-reference)
9. [Frontend Architecture](#9-frontend-architecture)
10. [Key Design Decisions](#10-key-design-decisions)

---

## 1. Full Pipeline Flow

The pipeline runs in a background thread (`api/pipeline_runner.py`) and emits Server-Sent Events to the browser. Each stage is timed and cached independently.

```
POST /api/search
  └─► pipeline_runner._execute_pipeline(search_id, query, category, rubric)
        │
        ├─ [CACHE CHECK] SHA256(query|category|rubric_weights|interview_Q&A) → 4h TTL
        │   Key uses interview Q&A only — NOT preferences_summary — so memory
        │   augmentation never busts the cache (fix R2).
        │   hit → replay cached result, return immediately
        │
        ├─ Stage 1: reddit_fetch.fetch_all_threads(enriched_query, limit, profile)
        │   ├── _build_retrieval_query(query, profile) — appends usage pattern
        │   │   from intent.preferences or preferences_summary to query
        │   │
        │   ├── _query_variations(query, profile) — profile-aware semantic variants:
        │   │     [base, +recommendation, +review, +vs]
        │   │     + usage pattern variant (gaming / gym / commuting / travel / …)
        │   │     + budget variant if intent.budget is set
        │   │     + region variant (india / uk / australia / worth it)
        │   │
        │   ├── Serper search for Reddit URLs across all variants (or PRAW if USE_PRAW=true)
        │   ├── _score_and_rank_urls() — subreddit relevance + title token overlap
        │   ├── fetch_thread_comments() — 2-pass: top + controversial sort, flatten tree
        │   └── Returns: list[Thread] (title, body, comments[], score)
        │
        ├─ Stage 1b: _dedup_threads(threads)
        │   Removes near-duplicate Reddit threads before summarization.
        │   Jaccard title-word overlap > 60% → keep higher-scored thread.
        │   Saves ~1-3 LLM summarization calls per run.
        │
        ├─ Stage 2: thread_summarizer.summarize_threads_parallel(threads)
        │   ├── ThreadPoolExecutor(max_workers=5)
        │   ├── One `thread_summarizer` agent call per thread
        │   ├── Provider pool: groq/cerebras/gemini/mistral round-robin
        │   └── Returns: list[ThreadSummary] (products, takeaways, quotes)
        │
        ├─ Stage 3: review_fetch.fetch_review_pages(query, category, region)
        │   ├── Category-aware site list (wirecutter, rtings, for tech; nytimes, epicurious for home)
        │   ├── Gemini grounding OR Serper search for review URLs
        │   ├── BeautifulSoup scrape, authority tier annotation
        │   └── domain_blacklist skips domains with >70% failure rate
        │
        ├─ Stage 4: llm_client.analyze_sources(summaries + reviews, query, rubric)
        │   ├── _build_analyzer_hint(profile) — prefers structured intent fields
        │   │   (MUST/budget/preferences/exclusions) over raw text truncation
        │   ├── main_analyzer agent (gemini, 1M context)
        │   ├── Returns: {products[], materials[], summary}
        │   └── analysis_normalizer coerces any malformed LLM output
        │
        ├─ Stage 4b: mention_pipeline.run_mention_pipeline(threads, base_registry)
        │   ├── alias_resolver.coref_pass(products, threads, llm_client)
        │   │   └── LLM coreference: discovers aliases ("CMF Buds" → "CMF Buds Pro 2")
        │   │       and exclusions ("Buds Air 7" must not count inside "Buds Air 7 Pro")
        │   │       Builds ProductInfo registry with canonical names + aliases
        │   │
        │   ├── mention_counter.build_automaton(registry)
        │   │   └── Aho-Corasick automaton over all canonical names + aliases
        │   │       O(n) single-pass over each text; word-boundary enforced;
        │   │       overlapping spans deduped (longer match wins)
        │   │
        │   ├── mention_counter.count_across_threads(threads, registry, automaton)
        │   │   ├── Title + body: thread-level count (no sentiment)
        │   │   ├── Each comment: counted individually
        │   │   └── Exclusion pass: 30-char window check prevents sub-product count leaks
        │   │
        │   ├── sentiment_analyser.analyse_comment() — per comment that has a mention
        │   │   └── Hard cap: MAX_SENTIMENT_CALLS = 50 per session (prevents runaway cost)
        │   │
        │   └── Returns: {canonical_name: MentionResult}
        │       MentionResult: total_mentions, distinct_threads, distinct_comments,
        │                      positive, negative, neutral, sentiment_score, sentiment_records
        │
        ├─ Stage 5: scorer.score_all_products(products, rubric, research_text, user_intent)
        │   ├── _build_constraint_context(user_intent) — injects hard_constraints
        │   │   and exclusions as scoring overrides (score 1-3 on violated criteria)
        │   ├── _format_criterion_line() — uses criterion.rationale over description
        │   ├── SCORING_MODE=fast  → pure heuristic (instant)
        │   ├── SCORING_MODE=hybrid → LLM top-10, heuristic rest
        │   └── SCORING_MODE=llm   → full LLM scoring
        │
        ├─ Stage 6: cross_validate.validate(products, summaries)
        │   └── cross_validator agent: detects community bias, split signal
        │
        ├─ Stage 7: memory.enrich_with_memory(products, category, query)
        │   ├── embed(query) → pgvector/cosine nearest signals
        │   └── Annotates each product with prior memory status
        │
        └─ Stage 8: scorer.write_explanations(products, rubric, profile)
            └── explanation_writer agent per product (parallel, groq)
```

### SSE Event Types

| Type | Payload | Description |
|---|---|---|
| `stage_start` | `{stage, label}` | Stage begins |
| `stage_done` | `{stage, label, elapsed_s}` | Stage complete with timing |
| `progress` | `{stage, current, total, detail}` | Within-stage progress |
| `log` | `{message}` | Informational message |
| `error` | `{message}` | Non-fatal error |
| `done` | `{search_id}` | Pipeline complete |
| `heartbeat` | `{}` | Keep-alive every 15s |

---

## 2. Structured User Intent Model

Interview Q&A is summarized into a typed `UserIntent` object in a single LLM call.
This replaces the old flat `preferences_summary` text blob as the primary carrier of user requirements.

```python
UserIntent = {
    "hard_constraints": list[str],  # MUST/NEVER/required/allergic/can't/won't
    "budget":           str | None, # "under ₹5000" / "$200 max" / null
    "preferences":      list[str],  # clearly stated wants (not constraints)
    "exclusions":       list[str],  # soft rejections ("prefers not in-ear")
    "uncertainties":    list[str],  # hedged statements ("maybe", "I think")
}
```

### How intent flows through the system

```
interview.py:_summarize_and_extract_intent()
    └─► profile["intent"] = UserIntent

profile["intent"]
    ├─► rubric.py:_build_intent_context()
    │     Adds "HARD REQUIREMENTS" + "USER EXPLICITLY REJECTS" + "BUDGET"
    │     block to the rubric generation prompt → weights reflect actual requirements
    │
    ├─► pipeline_runner.py:_build_analyzer_hint()
    │     Formats intent as MUST:/Budget:/Wants:/Excludes: lines for the
    │     analyzer hint (prefers structured intent over raw text truncation)
    │
    ├─► pipeline_runner.py:_build_retrieval_query()
    │     Extracts usage pattern from intent.preferences to enrich the
    │     Reddit search query (e.g. "best earbuds" → "best earbuds gaming")
    │
    ├─► reddit_fetch.py:_query_variations()
    │     Adds a usage-pattern variant and a budget variant to the
    │     query variation set sent to Serper
    │
    └─► scorer.py:_build_constraint_context()
          Injects hard_constraints + exclusions as per-product scoring
          overrides: products that violate a constraint score 1-3 on the
          relevant criterion regardless of research text
```

### Backward compatibility

- `profile["preferences_summary"]` still set alongside `intent` for any
  code that reads it.
- `_summarize_preferences()` wrapper returns text only (used by old CLI paths).
- Saved profiles without `intent` fall back gracefully — all intent-aware
  functions gate on `profile.get("intent")`.

### Memory safety (B2 fix)

Memory context from past searches is appended **after** the current-session
`preferences_summary`, never prepended:

```python
merged = f"{current_session_summary}\n\nAdditional context from past searches:\n{memory_context}"
```

Cross-category signals are filtered before injection to prevent leakage.

---

## 3. Agent Registry

All agents are defined in `agents.py`. The agent name is the key; the value specifies the default provider, fallback chain, and behavior.

| Agent | Default Provider | Fallback Chain | Role |
|---|---|---|---|
| `category_detector` | groq | cerebras→gemini→mistral→openrouter | Query → category slug + region |
| `criteria_generator` | gemini | groq→cerebras→mistral→openrouter | Category → buying criteria list |
| `interview_questioner` | mistral | gemini→groq→cerebras→openrouter | Next adaptive question |
| `preference_summarizer` | mistral | gemini→groq→cerebras→openrouter | Q&A → `UserIntent` JSON + summary text (JSON mode, max_tokens=1024) |
| `rubric_generator` | gemini | groq→cerebras→mistral→openrouter | Profile + criteria → weights |
| `gap_filler` | gemini | groq→cerebras→mistral→openrouter | Fill uncovered criteria from research |
| `thread_summarizer` | **pool** | groq→cerebras→gemini→mistral→openrouter | One thread → structured summary |
| `main_analyzer` | gemini | groq→cerebras→mistral→openrouter | All summaries → ranked products |
| `product_scorer` | groq | cerebras→gemini→mistral→openrouter | Product → per-criterion scores |
| `explanation_writer` | groq | cerebras→mistral→gemini→openrouter | Product → "why this fits you" |
| `cross_validator` | gemini | groq→cerebras→mistral→openrouter | Cross-subreddit bias detection |
| `signal_extractor` | groq | cerebras→gemini→mistral→openrouter | Q&A → durable preference signals |

### Provider Pool (thread_summarizer)

The `thread_summarizer` uses `provider: "pool"` which distributes calls cyclically across all 4 fast providers. With 15 threads and 4 providers, each provider handles ~3-4 threads concurrently. Effective rate limit is 4× any single provider.

```python
# Round-robin assignment
_provider_cycle = itertools.cycle(["groq", "cerebras", "gemini", "mistral"])
provider = next(_provider_cycle)
```

### run_agent()

```python
def run_agent(agent_name: str, user_prompt: str, system: str = "") -> str:
    agent = AGENTS[agent_name]
    provider = _pick_provider(agent)   # respects circuit breaker + dead list
    try:
        return _call_provider(provider, user_prompt, system, agent)
    except RateLimitError:
        return run_agent_with_fallback(agent_name, user_prompt, system, skip=provider)
    except ProviderAuthError:
        mark_provider_dead(provider)
        return run_agent_with_fallback(...)
```

---

## 3. LLM Provider Failover

### Circuit Breaker (`llm_clients.py`)

Each provider has an independent rolling window circuit breaker:

```
Window size: 10 calls
Trip threshold: 50% failures within window
Short cooldown (429): 60 seconds
Long cooldown (502/503): 120 seconds
Auth error (401/403): permanent session-dead (no retry)
```

State transitions:
```
CLOSED → (≥5 failures in 10 calls) → OPEN (blocked for 60-120s)
OPEN   → (timer expires)           → HALF-OPEN (next call probes)
HALF-OPEN → (success)              → CLOSED
HALF-OPEN → (failure)              → OPEN (reset timer)
```

### Smart Retry (`_smart_post_with_retry`)

```python
Attempt 1 → 429 → wait 2s → Attempt 2 → 429 → wait 5s → Attempt 3
                                                           → trip circuit 60s

Attempt 1 → 502 → record failure → raise (no retry, let fallback chain handle)
Attempt 1 → 401 → raise ProviderAuthError → mark provider dead permanently
Attempt 1 → timeout → raise fast (no retry at this level)
```

### Provider Status API

`GET /api/providers/status` returns per-provider:
```json
{
  "providers": {
    "groq": {
      "configured": true,
      "session_alive": true,
      "circuit_blocked": false,
      "circuit_detail": {
        "blocked": false,
        "blocked_until": 0,
        "reason": "",
        "success_rate": 0.92,
        "recent_calls": 12
      }
    }
  }
}
```

---

## 4. Memory Layer

### Storage

**SQLite (default):** embeddings stored as JSON arrays, cosine similarity computed in Python.

**PostgreSQL + pgvector (production):** embeddings stored as `vector(768)` columns, similarity search uses `<=>` operator (IVFFlat index for scale).

### Embedding Chain

```
embed(text):
  1. Gemini text-embedding-004 → 768-dim vector
  2. (fallback) Cohere embed-english-v3.0 (COHERE_API_KEY)
  3. (fallback) HuggingFace sentence-transformers API (HF_API_KEY)
  4. (fallback) Local sentence-transformers (auto-downloaded)
```

All results are SHA256-cached in memory (LRU, unbounded within session).

### Signal Types

| Signal Type | Example | Strength |
|---|---|---|
| `preference` | "I prioritize bass over clarity" | strong/moderate |
| `rejection` | "ANC hurts my ears" | strong |
| `purchase` | "Bought Sony WF-C700N" | strong |
| `complaint` | "Cable broke after 3 months" | moderate |

### Memory Context Retrieval

At pipeline start, `memory.get_context(category, query)` returns:
1. Top-5 signals by cosine similarity to current query
2. All product memories for this category
3. A `profile_summary` string injected into the rubric generation prompt

---

## 5. Scoring Algorithm

### Hybrid Mode (default)

```python
def score_all_products(products, rubric, research_text, mode="hybrid"):
    if mode == "fast":
        return [_fast_score(p, rubric) for p in products]
    
    if mode == "hybrid":
        top10 = products[:10]
        rest = products[10:]
        llm_scored = _run_parallel_batch_scoring(top10, rubric, research_text)
        fast_scored = [_fast_score(p, rubric) for p in rest]
        return llm_scored + fast_scored
    
    if mode == "llm":
        return _run_parallel_batch_scoring(products, rubric, research_text)
```

### Fast Heuristic (`_fast_score`)

```python
base = 5.0
mention_boost  = min(mentions / 10, 2.0)      # up to +2 for 10+ mentions
sentiment_mod  = (pos - neg) / max(total, 1)  # -1 to +1
signal_mod     = {"high": 1.0, "medium": 0.5, "low": -0.5}[signal_strength]
raw_score      = base + mention_boost + sentiment_mod + signal_mod
per_criterion  = clamp(raw_score, 1, 10)
```

Weights are then applied identically to LLM scores:
```python
weighted_total = sum(criterion.weight * score.score for score in product.scores)
percentage = weighted_total / max_possible * 100
```

### LLM Scoring Prompt

Each `product_scorer` call receives:
- Product name + mention counts + pos/neg ratio
- Rubric with weights and criterion descriptions
- Full research text (capped at context limit)
- Returns: `[{criterion, score: 1-10, evidence: "quote from research"}]`

### Re-ranking (Frontend)

The browser receives the full `{scores, weights}` object. `rerank.ts`:

```typescript
function rerank(products: Product[], weights: Record<string, number>): Product[] {
  return [...products]
    .map(p => ({
      ...p,
      score: p.criteriaScores.reduce((sum, s) => sum + weights[s.criterion] * s.score, 0)
    }))
    .sort((a, b) => b.score - a.score)
}
```

Called synchronously on every slider change. No debounce needed — runs in <5ms.

---

## 6. Database Schema

### SQLite (default)

```sql
CREATE TABLE Search (
    id          TEXT PRIMARY KEY,     -- cuid
    query       TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT '',
    region      TEXT NOT NULL DEFAULT 'global',
    status      TEXT NOT NULL DEFAULT 'pending', -- pending|running|done|error
    createdAt   TEXT NOT NULL,        -- ISO 8601
    profile     TEXT,                 -- JSON
    rubric      TEXT,                 -- JSON: {weighted_criteria[]}
    analysis    TEXT,                 -- JSON: {products[], materials[], summary}
    scoredProducts TEXT,              -- JSON: ScoredProduct[]
    explanations   TEXT,              -- JSON: {productName: explanation}
    shoppingLinks  TEXT               -- JSON: {productName: url}
);

CREATE TABLE Profile (
    category    TEXT PRIMARY KEY,     -- e.g. "earphones/wireless"
    data        TEXT NOT NULL,        -- JSON: {preferences, qa_history, ...}
    updatedAt   TEXT NOT NULL
);

CREATE TABLE UserSignal (
    id             TEXT PRIMARY KEY,
    userId         TEXT NOT NULL DEFAULT 'default',
    signalType     TEXT NOT NULL,     -- preference|rejection|purchase|complaint
    productName    TEXT,
    category       TEXT,
    text           TEXT NOT NULL,     -- natural language signal
    embedding      TEXT,              -- JSON float array [768 dims]
    strength       TEXT NOT NULL DEFAULT 'moderate',
    sourceSearchId TEXT,              -- which search generated this
    createdAt      TEXT NOT NULL
);

CREATE TABLE ProductMemory (
    id           TEXT PRIMARY KEY,
    userId       TEXT NOT NULL DEFAULT 'default',
    productName  TEXT NOT NULL,
    category     TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'considered', -- considered|rejected|purchased|returned
    ourScore     REAL,
    userFeedback TEXT,
    createdAt    TEXT NOT NULL,
    UNIQUE(userId, productName)
);
```

### PostgreSQL (pgvector)

Same schema with these differences:
- `embedding` is `vector(768)` instead of `TEXT`
- Timestamps are `TIMESTAMPTZ` with `DEFAULT now()`
- Cosine similarity: `1 - (embedding <=> $1::vector)` with IVFFlat index

---

## 7. API Endpoint Reference

Base URL: `http://localhost:8000`

### Search / Pipeline

| Method | Path | Body / Params | Response |
|---|---|---|---|
| `POST` | `/api/search` | `{query, category, region, rubric}` | `{search_id}` |
| `GET` | `/api/search/:id/stream` | — | SSE stream |
| `GET` | `/api/search/:id` | — | Full `SearchResult` |
| `GET` | `/api/searches` | `?limit=20` | `{searches: SearchResult[]}` |

### Profile & Interview

| Method | Path | Body | Response |
|---|---|---|---|
| `POST` | `/api/detect` | `{query}` | `{category, region, needs_disambiguation}` |
| `POST` | `/api/criteria` | `{category}` | `{criteria: Criterion[]}` |
| `POST` | `/api/interview/next` | `{category, qa_history[]}` | `{question, why_asking, is_done}` |
| `POST` | `/api/interview/summarize` | `{category, qa_history[]}` | `{preferences_summary, intent: UserIntent}` |
| `POST` | `/api/rubric` | `{category, profile, criteria}` | `{rubric: Rubric}` |
| `GET` | `/api/profile/:category` | — | Profile dict |
| `POST` | `/api/profile/:category` | Profile dict | `{ok}` |

### Prices & Memory

| Method | Path | Body / Params | Response |
|---|---|---|---|
| `POST` | `/api/prices` | `{products: string[], region}` | `{prices: ProductPrice[]}` |
| `GET` | `/api/memory/context` | `?category=&query=` | `{signals, profile_summary, has_memory}` |
| `GET` | `/api/memory/signals` | `?category=` | `{signals: UserSignal[]}` |
| `DELETE` | `/api/memory/signals/:id` | — | `{deleted}` |
| `GET` | `/api/memory/products` | `?status=` | `{products: ProductMemory[]}` |
| `POST` | `/api/memory/products/:name/status` | `{status}` | `{ok}` |
| `POST` | `/api/memory/bought` | `{product_name, category, feedback}` | `{ok}` |
| `DELETE` | `/api/memory/all` | — | `{deleted}` |

### Observability

| Method | Path | Response |
|---|---|---|
| `GET` | `/api/providers/status` | Per-provider `{configured, session_alive, circuit_blocked, circuit_detail}` |
| `GET` | `/api/health` | `{status, db, providers}` |

---

## 8. Frontend Architecture

### State Management

```
useResultsStore (Zustand)         useAppStore (Zustand)
├── rubric                        ├── searchHistory[]
├── weights (live)                └── addSearchHistory()
├── products[]                    
├── compareSet                    SWR hooks (lib/hooks.ts)
├── initResults()                 ├── useSearchHistory()
├── setWeight()                   ├── useSearch(id)
├── resetWeights()                ├── useMemorySignals()
└── toggleCompare()               └── useProviderStatus()
```

### Re-ranking Flow

```
Slider drag → setWeight(criterionId, value)
           → Zustand updates weights
           → useDeferredValue(products) triggers re-sort
           → displayProducts memo recomputes
           → AnimatePresence layout animation
```

`useDeferredValue` ensures rapid slider drags don't cause layout thrash — React defers the expensive re-sort to idle time while keeping the slider itself responsive.

### SSE Pipeline Streaming

`/research` page:
1. `POST /api/search` → `search_id`
2. `EventSource(/api/search/:id/stream)` → renders stage progress
3. On `done` event → navigate to `/results/:id`
4. Results page fetches full JSON once, stores in Zustand

---

## 9. Key Design Decisions

**Why SQLite as default instead of Postgres?**  
Zero setup for new users. pgvector requires Docker and Postgres 15+. For single-user local use, SQLite with in-memory cosine search is fast enough (<100ms for 10k signals). Switch to Postgres by setting `POSTGRES_URL`.

**Why parallel per-thread summarizers instead of one big analysis call?**  
Feeding 15 raw threads (150K+ chars) to one LLM call causes context overload — the model loses detail from early threads by the time it reaches later ones. Smaller focused context → better extraction. Parallel execution → bounded by slowest thread, not sum of all.

**Why no PyTorch / heavy ML dependencies?**  
Cosine similarity is 5 lines of Python math. The heavy ML work is done by the embedding API providers. Adding PyTorch would be a 2GB install for a function that can be implemented as `dot(a, b) / (norm(a) * norm(b))`.

**Why OpenRouter as the final fallback?**  
OpenRouter provides access to 100+ models under one API key. Even with a completely fresh `.env` (no Groq/Gemini/etc.), a single `OPENROUTER_API_KEY` makes the entire system work. It's the "guaranteed to work" floor.

**Why `SCORING_MODE=hybrid` as default?**  
Full LLM scoring of 15+ products × 6 criteria = 90+ LLM calls per run. Hybrid mode (LLM for top 10, heuristic for rest) reduces this to ~60 calls with negligible quality loss — the bottom 5 products rarely change the recommendation. Fast mode is useful for demos and development.
