# ShopSense — Multi-Agent AI Shopping Research System

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-000000?logo=next.js)](https://nextjs.org)
[![TypeScript](https://img.shields.io/badge/TypeScript-strict-3178C6?logo=typescript&logoColor=white)](https://typescriptlang.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **12 specialized AI agents. 5 LLM providers with automatic failover. 15 Reddit threads + expert reviews synthesized in parallel. Personalized rubric scoring. Live re-ranking with zero API calls.**
>
> Not a chatbot. Not a product listing aggregator. A research pipeline that does what a thorough human researcher would do in 3 hours — in 85 seconds.

---

## The Problem

Every "best X" article is SEO bait. Reddit has real signal but reading 15 threads to find one product takes hours. AI chatbots hallucinate prices, recommend discontinued items, and give the same answer to everyone regardless of their specific needs.

**ShopSense is different at the architectural level:**

- Fetches real data (Reddit + trusted review sites) instead of relying on training knowledge
- Personalizes through a structured interview — builds a weighted rubric per user, not generic recommendations
- Runs deterministic mention counting using Aho-Corasick automaton — no LLM estimation of "how many people mentioned this"
- Detects community bias by comparing sentiment across subreddits before surfacing conclusions
- Learns across searches via vector memory — never asks what you already told it

---

## End-to-End Pipeline

```
Query: "best wireless earbuds under ₹3000 for gym"
  │
  ├─ [1] CATEGORY DETECTION  ──────────────────────── Groq Llama 70B
  │       earphones · wireless · budget-india
  │
  ├─ [2] CRITERIA GENERATION ──────────────────────── Gemini (cached)
  │       6–10 buying criteria specific to this category
  │       e.g. sound_quality, comfort, battery_life, mic_quality, fit_security
  │
  ├─ [3] ADAPTIVE INTERVIEW ───────────────────────── Mistral Small
  │       4–8 questions, coverage-aware termination
  │       Builds UserIntent: {hard_constraints, budget, preferences, exclusions}
  │       Memory injection: skips questions user answered in past searches
  │
  ├─ [4] RUBRIC GENERATION ────────────────────────── Gemini
  │       Assigns weight 0–10 per criterion based on interview
  │       Gap-fill: infers weights for uncovered criteria using research signal
  │       e.g. sound_quality: 9, comfort: 8, mic_quality: 3, price_to_value: 7
  │
  ├─ [5] PARALLEL RESEARCH ────────────────────────── ThreadPoolExecutor
  │   │
  │   ├─ REDDIT (15 threads)
  │   │   3 query variants × 5 subreddit targets
  │   │   Budget/region/use-case variants injected from UserIntent
  │   │   Comment tree flattening (3 levels, top-sorted, 100 comments max)
  │   │   Jaccard dedup: overlapping threads removed before summarization
  │   │
  │   └─ REVIEWS (6–8 sites)
  │       Gemini grounding (live Google Search) finds authoritative sources
  │       Jina Reader fallback for JS-heavy or 403-blocked pages
  │       Authority tier tagging: TRUSTED / GOOD / UNKNOWN
  │
  ├─ [6] PARALLEL SUMMARIZATION ───────────────────── Provider Pool (4×)
  │       1 sub-agent per Reddit thread (ThreadPoolExecutor, max 5 workers)
  │       Round-robin across [Groq, Gemini, Mistral] → 4× effective rate limit
  │       Input: 10K chars raw thread → Output: structured summary
  │       {products_mentioned, key_takeaways, top_comments, controversial_signals}
  │       150K chars raw → 30K chars structured (80% compression, higher quality)
  │
  ├─ [7] MENTION COUNTING ─────────────────────────── Python (no LLM)
  │       Alias discovery: LLM extracts all names for each product
  │       Aho-Corasick automaton: O(n) single-pass match across all aliases
  │       Overlapping-span dedup: "Buds Air 7 Pro" beats "Buds Air 7" at same position
  │       Distinct recommenders counted (comments, not raw mentions)
  │
  ├─ [8] CROSS-SUBREDDIT VALIDATION ──────────────── Groq
  │       Compares product sentiment across communities
  │       Flags split signal: "praised in r/budgetaudiophile, mixed in r/audiophile"
  │       Requires 2+ subreddits AND 3+ total mentions before firing
  │       Result: consistent / split / single_source per product
  │
  ├─ [9] MAIN ANALYSIS ────────────────────────────── Gemini 2.5 Flash (1M ctx)
  │       Aggregates structured summaries + authority-tagged reviews
  │       Separates materials (category types) from products (buyable items)
  │       Applies source weighting: TRUSTED > GOOD > UNKNOWN
  │       Budget enforcement: rejects out-of-range products at prompt level
  │
  ├─ [10] SCORING (hybrid mode) ───────────────────── Groq (parallel batches)
  │        Top 10 products: full LLM scoring — 0–10 per criterion with evidence
  │        Remaining products: instant heuristic (sentiment ratio × volume bonus)
  │        Hard constraint enforcement: MUST violation → forced 1–3 score
  │        Batch mode: 3 products per LLM call → 3× fewer requests
  │
  ├─ [11] ENRICHMENT ──────────────────────────────── Parallel
  │        Price fetch: Amazon.in / Flipkart via Serper (real-time)
  │        Memory lookup: pgvector cosine similarity (k=5, threshold 0.7)
  │        Explanation: "Why this fits you" per product (Groq)
  │
  └─ [12] RESULTS UI
          Products ranked by weighted score
          Live sliders → instant re-ranking (pure JS, <5ms, zero API calls)
          Framer Motion spring physics animates position changes
          ⌘K command palette, compare mode, community signal badges
```

---

## 12 Specialized Agents

Each agent is tuned to its task — different provider, temperature, and prompt strategy.

| Agent | Primary Provider | Temperature | Task |
|---|---|---|---|
| `category_detector` | Groq Llama 70B | 0.1 | Query classification + region detection |
| `criteria_generator` | Gemini 2.5 Flash | 0.4 | Generate 6–10 buying criteria per category |
| `interview_questioner` | Mistral Small | 0.7 | Generate conversational interview questions |
| `interview_classifier` | Groq Llama 70B | 0.1 | Classify message: ANSWER/QUESTION/SKIP/COMMAND |
| `preference_summarizer` | Groq Llama 70B | 0.2 | Extract structured UserIntent from Q&A |
| `rubric_generator` | Gemini 2.5 Flash | 0.3 | Build weighted scorecard from criteria + profile |
| `gap_filler` | Groq Llama 70B | 0.3 | Infer weights for uncovered criteria |
| `thread_summarizer` | Pool (Groq/Gemini/Mistral) | 0.2 | Summarize one Reddit thread → structured data |
| `main_analyzer` | Gemini 2.5 Flash | 0.3 | Aggregate summaries + reviews → product list |
| `product_scorer` | Groq Llama 70B | 0.1 | Score product 0–10 per criterion with evidence |
| `explanation_writer` | Groq Llama 70B | 0.5 | "Why this product fits you" per result |
| `cross_validator` | Groq Llama 70B | 0.2 | Explain community sentiment disagreement |

---

## 5-Provider Failover Architecture

All 5 providers use free tiers. No paid API required.

```
Groq (llama-3.3-70b-versatile)          ← fastest, primary for most agents
  │  fail: quota / 429
  ▼
Cerebras (llama-3.1-8b)                  ← ultra-fast inference, 1 attempt only
  │  fail: quota / 429
  ▼
Gemini 2.5 Flash (google/gemini-flash)  ← 1M context, best for large payloads
  │  fail: quota / 429
  ▼
Mistral Small (mistral-small-latest)    ← natural conversational tone
  │  fail: quota / 429
  ▼
OpenRouter (routed to best available)   ← master fallback, never skipped
```

**Circuit Breaker**: 429/502/503 errors trip a provider for 60–120 seconds. After cooldown, it auto-retries. If a provider returns 401/403, it's marked session-dead and skipped for the entire run.

**Consecutive Failure Threshold**: 3 consecutive failures on any provider → auto-marked dead. `reset_dead_providers()` clears counters between searches.

**Provider-Aware Token Budgets**: Before each call, the active provider's context limit is checked. Research text windows resize dynamically — Groq gets 2.5K chars/product, Gemini gets 6K chars/product.

**Round-Robin Pool** (thread summarization): `thread_summarizer` uses `provider="pool"` cycling across [Groq, Gemini, Mistral]. 15 threads × 4 providers = 4× effective rate limit. Thread-safe cycling counter per pool agent.

---

## Structured UserIntent Model

The interview produces a typed intent object, not a flat text blob. Every downstream component reads fields directly instead of re-parsing unstructured text.

```python
UserIntent = {
    "hard_constraints": ["lightweight — must be under 30g", "no in-ear style"],
    "budget":           "under ₹3000",
    "preferences":      ["bass-heavy", "good for gym/running", "long battery"],
    "exclusions":       ["prefers no Chinese brands"],
    "uncertainties":    ["maybe ANC if in budget"]
}
```

**How intent flows through the system:**

- `rubric_generator` → hard constraints weight to 9–10; exclusions weight to 1–2
- `main_analyzer` → MUST/Budget/Wants/Excludes injected as structured override block
- `product_scorer` → constraint violations force score to 1–3 regardless of evidence
- `gap_filler` → uses intent + research signal to infer weights for criteria user didn't address
- `criteria.py` → `price_to_value` auto-marked covered when budget is in query (budget implies price awareness)

---

## Aho-Corasick Mention Counting

One of the most underrated parts of the system. LLM-estimated mention counts are unreliable — they conflate "X" and "Brand X" and miss abbreviations. ShopSense uses a deterministic automaton instead.

**Three-phase pipeline:**

1. **Alias Discovery** — per-thread LLM call finds all ways a product was referred to: "WF-1000XM5", "XM5", "Sony XM5", "the Sony ones", etc.

2. **Automaton Build** — all product names + aliases compiled into an Aho-Corasick multi-pattern automaton. Single O(n) pass over the full comment corpus, no nested regex loops.

3. **Span Deduplication** — when overlapping matches exist at the same position ("Buds Air 7 Pro" and "Buds Air 7"), the longer match wins. Exclusion-pattern cancellation: "Air 7 Pro" suppresses any nearby "Air 7" match within a 30-character window.

**Result**: deterministic integer counts — not LLM estimates. Distinct recommenders counted per comment (prevents 1 user with 10 mentions counting as 10 recommenders).

---

## Cross-Subreddit Bias Detection

A product praised in r/budgetaudiophile but criticized in r/audiophile needs investigation — they may be evaluating it against different reference points.

```
Product: Sony WF-C700N

  r/IndianGaming       →  positive  (3 mentions)
  r/budgetaudiophile   →  positive  (4 mentions)
  r/audiophile         →  mixed     (1 pos, 3 neg)

  Signal: "split"
  Explanation: "Audiophile community criticizes compressed soundstage vs similarly-priced
                wired options; gaming and budget communities weigh ANC and price more heavily."
  Context note: "If audio accuracy matters, research further. If ANC and call quality are
                 the priority, community consensus is positive."
```

Requires 2+ subreddits AND 3+ total mentions before firing the LLM call. Single-source products get `"signal": "single_source"` rather than a forced explanation.

---

## Parallel Thread Summarization

The naive approach — dump 15 threads (≈150K chars) into one LLM call — wastes context and produces lower-quality extraction. The cognitive load on the model is too high.

**ShopSense approach:**
- Spawn one `thread_summarizer` sub-agent per thread
- Each agent sees ≤10K chars (one focused thread)
- All run in parallel (`ThreadPoolExecutor`, max 5 workers)
- Total wall time = slowest thread, not sum of all threads

**Per-thread output:**
```python
{
  "thread_summary":       "2-sentence neutral summary",
  "products_mentioned":   [{"name": ..., "sentiment": ..., "mention_count": ..., "key_quotes": [...]}],
  "key_takeaways":        ["top insight", "notable disagreement"],
  "top_comments":         [{"text": "verbatim quote", "upvotes": N}],
  "controversial_signals":["specific complaint with high upvotes despite disagreement"]
}
```

**Compression ratio**: 150K chars raw → ~30K chars structured. Main analyzer gets clean, focused input rather than noisy raw comments.

---

## Three-Mode Scoring System

| Mode | Method | Speed | Quality |
|---|---|---|---|
| `fast` | Pure Python heuristic | Instant | Lower |
| `hybrid` | LLM for top 10, heuristic for rest | ~45s | High where it matters |
| `llm` | Full LLM for every product | ~90s | Highest |

**Default: `hybrid`**. Products the user is most likely to care about get rigorous LLM scoring. The long tail gets a fast heuristic that's accurate enough for filtering.

**Heuristic formula (fast/hybrid tail):**
```
base_score = (positive_mentions / total_mentions) × 10
volume_bonus:  +1.0 if 20+ mentions  |  +0.5 if 10+  |  +0.2 if 5+  |  -0.5 if <5
signal_mod:    +0.5 high/medium  |  -0.5 low
final = clamp(base_score + volume_bonus + signal_mod, 0, 10)
```

**LLM scoring features:**
- Batch mode: 3 products per call (3× fewer requests)
- Evidence citations: "8 users report 6+ hours battery" not generic praise
- Constraint override: MUST violation → forced 1–3 regardless of evidence
- Rate-limited: 6s between calls for free-tier Groq

---

## Live Re-ranking: Zero API Calls

The full rubric (criteria + weights) and per-product scores are loaded into the browser once. When a user drags a slider, `rerank.ts` recomputes the weighted sum across all products:

```
weighted_score = Σ (criterion_score × criterion_weight) / Σ weights
```

Products animate into new positions using Framer Motion spring physics. No debounce required — computation finishes in <5ms for 20 products. No server contact, no API cost.

This means users can explore "what if I cared more about battery life?" or "what if price doesn't matter?" instantly, without waiting for a new research run.

---

## Vector Memory Across Searches

Durable user signals are embedded and stored between searches. Transient context (current budget, current search intent) is never persisted.

**What gets saved:**
- Physical traits: "has sensitive ears", "allergic to latex"
- Lifestyle patterns: "gym 5 days/week", "commutes 2 hours daily"
- Strong preferences: "always prefers Japanese brands", "never buys open-back"

**What doesn't:**
- Current budget (changes per search)
- Current query intent
- Scores and results from past searches

**Retrieval:** `find_relevant_signals(query, k=5, min_similarity=0.7)` — pgvector cosine similarity at the DB layer. Cross-category signals filtered before injection. When surfaced, the interview questioner uses them to skip redundant questions or pre-fill context.

**Embedding chain:** Gemini `text-embedding-004` (768-dim) → Cohere → HuggingFace → local `sentence-transformers`

---

## Smart Caching Strategy

| What | Key | TTL |
|---|---|---|
| Pipeline results | SHA256(query + category + rubric weights + Q&A) | 4h |
| Thread content | URL hash | 24h |
| Review page content | URL hash | 24h |
| Review URLs | query + category | 4h |
| Criteria | category slug | Until count <6 |
| Embeddings | text SHA256 | No expiry |

**Key insight on pipeline cache key:** the key includes interview Q&A (not `preferences_summary`). Memory context injection changes the summary text but not the Q&A, so memory augmentation never busts the cache.

---

## Tech Stack

### Backend
- Python 3.11+, FastAPI 0.115, Uvicorn
- PostgreSQL 16 + pgvector (production) | SQLite (dev)
- Server-Sent Events for real-time pipeline streaming
- `ThreadPoolExecutor` — no async overhead, simple parallel execution
- `pyahocorasick` — Aho-Corasick multi-pattern automaton
- BeautifulSoup, requests, Jina Reader (JS-heavy page fallback)
- slowapi rate limiting (200 req/min per IP)

### Frontend
- Next.js 16 (App Router), TypeScript strict
- Tailwind CSS v4, shadcn/ui (47 Radix-based components)
- Framer Motion (spring physics for live re-ranking animation)
- Zustand (client state), SWR (server cache)
- `cmdk` — ⌘K command palette
- `recharts` — score visualization

### LLM Providers (all free tier)
| Provider | Model | Primary Use |
|---|---|---|
| Groq | llama-3.3-70b-versatile | Scoring, classification, interview |
| Cerebras | llama-3.1-8b | Alternate fast inference |
| Google Gemini | gemini-2.5-flash | Source analysis (1M ctx), rubric |
| Mistral | mistral-small-latest | Interview questions (conversational) |
| OpenRouter | routed | Master fallback |

### External APIs
| API | Use | Cost |
|---|---|---|
| Gemini grounding | Review site discovery via Google Search | Free |
| Serper | Reddit thread search, review URL backup | 2500/mo free |
| PRAW (optional) | Deep Reddit archive (200+ comments/thread) | Free |
| Gemini Embeddings | `text-embedding-004` (768-dim) | Free |

---

## Quick Start

### Prerequisites
- Python 3.11+, Node.js 18+
- At minimum: one free key from [Groq](https://console.groq.com) or [Gemini](https://aistudio.google.com/apikey)

### 1. Clone and configure
```bash
git clone https://github.com/Om-5640/shopsense.git
cd shopsense
cp .env.example .env
```

Edit `.env` — minimum viable setup:
```bash
GEMINI_API_KEY=AIza...        # free at aistudio.google.com
GROQ_API_KEY=gsk_...          # free at console.groq.com
SERPER_API_KEY=...            # free at serper.dev (2500/mo)
OPENROUTER_API_KEY=sk-or-...  # free at openrouter.ai
```

### 2. Start the API
```bash
cd api
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### 3. Start the UI
```bash
cd web
cp .env.example .env.local
pnpm install && pnpm dev
```

Open [http://localhost:3000](http://localhost:3000)

### 4. Or use the CLI
```bash
python run.py "best earbuds under ₹3000"
python run.py "best mechanical keyboard" --no-reviews
python run.py "best winter blanket" --skip-interview
python run.py "best budget laptop" --output results.json --scoring-mode llm
```

### 5. With Docker (PostgreSQL + pgvector)
```bash
docker-compose up -d
# Postgres on 5433, pgvector enabled
```

---

## Pages

| Route | Description |
|---|---|
| `/` | Search home, recent history |
| `/research?q=` | Live pipeline with SSE progress stream |
| `/results/:id` | Ranked products, live sliders, community data |
| `/compare?ids=` | Side-by-side product comparison grid |
| `/history` | All past searches, resumable |
| `/memory` | Your preference signals + product memories |
| `/settings` | Provider health, circuit breaker state |

---

## API Reference

```
POST /api/search              → start pipeline, returns search_id
GET  /api/search/:id/stream   → SSE: live stage events + progress
GET  /api/search/:id          → full result JSON
GET  /api/searches            → paginated history
POST /api/prices              → real-time price lookup
GET  /api/memory/context      → relevant signals for a query
GET  /api/providers/status    → per-provider health + circuit state
GET  /api/health              → liveness check
```

---

## Key Configuration

| Variable | Default | Effect |
|---|---|---|
| `SCORING_MODE` | `hybrid` | `fast` / `hybrid` / `llm` |
| `USE_PRAW` | `false` | Enable PRAW deep Reddit (needs Reddit app creds) |
| `POSTGRES_URL` | unset | Use PostgreSQL + pgvector instead of SQLite |
| `MAX_REDDIT_THREADS` | `15` | Threads fetched per search |
| `MAX_REVIEW_SITES` | `8` | Review pages scraped per search |

---

## Project Structure

```
shopsense/
├── api/
│   ├── main.py              REST + SSE endpoints, rate limiting, session management
│   ├── db.py                Dual-backend ORM (SQLite / Postgres + pgvector)
│   └── pipeline_runner.py   Pipeline orchestration, SSE event queue, stage timing
│
├── web/
│   ├── app/                 Next.js App Router pages
│   ├── components/          47 Radix-backed UI components
│   └── lib/                 store.ts · api.ts · rerank.ts · hooks.ts
│
├── agents.py                Agent registry, fallback chains, provider pool
├── llm_clients.py           5-provider facade, circuit breaker, retry logic
├── llm_client.py            Gemini primary analyzer, SUMMARIES_ANALYZER_SYSTEM
├── interview.py             Adaptive interview, coverage-aware termination, UserIntent
├── criteria.py              Category-specific buying criteria (cached)
├── rubric.py                Personalized weighted scorecard + gap-fill
├── scorer.py                3-mode scoring: llm / hybrid / fast heuristic
├── thread_summarizer.py     Parallel sub-agent summarization, provider pool
├── cross_validate.py        Cross-subreddit community bias detection
├── mention_counter.py       Aho-Corasick automaton, alias resolution
├── alias_resolver.py        Per-thread LLM alias discovery
├── memory.py                Signal extraction, pgvector storage + retrieval
├── embeddings.py            Multi-provider embedding service with fallback
├── reddit_fetch.py          Multi-variant Reddit search (Serper + PRAW)
├── review_fetch.py          Gemini grounding + Serper, Jina Reader fallback
├── source_filter.py         Domain authority tiers, affiliate junk filter
├── domain_blacklist.py      Auto-blacklist for high-failure-rate domains
├── prompt_builder.py        Research context assembly, token budget management
├── price_fetcher.py         Real-time Amazon.in / Flipkart price scraping
└── run.py                   CLI orchestrator
```

---

## Design Decisions Worth Knowing

**Why parallel summarization instead of one big LLM call?**
Focused context produces better extraction. A model reading one 8K-char thread finds products more accurately than one reading 15 threads in 150K chars. Parallel execution means total wall time is bounded by the slowest thread, not their sum.

**Why Aho-Corasick instead of asking the LLM to count mentions?**
LLM mention counts are estimates. They conflate product aliases, miss abbreviations, and hallucinate counts under pressure. Aho-Corasick gives exact integers — deterministic, auditable, fast.

**Why structured UserIntent instead of flat preferences text?**
Every downstream component (rubric generator, scorer, analyzer) needs to act differently on hard constraints vs. soft preferences vs. exclusions. A flat text blob forces each component to re-parse. A typed dict with known fields means constraint enforcement is reliable and explicit.

**Why not async?**
Thread pools are simpler, debuggable, and sufficient for the I/O profile. No async libraries, no event loop debugging, no `await` chains. Rate limiting is handled at the provider layer, not at the concurrency layer.

**Why hybrid scoring instead of always LLM?**
A user searching earbuds cares about the top 5 results, not whether #18 scored 4.2 or 4.4. LLM scoring where it matters (top 10), fast heuristics where it doesn't. 45 seconds instead of 120 seconds for the default path.

---

## License

MIT — see [LICENSE](LICENSE).
