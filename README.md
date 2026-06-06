<div align="center">

# ShopSense

### A multi-agent AI research pipeline that does 3 hours of human product research in ~85 seconds — and continuously scores its intelligence through a self-grading 9-metric Intelligence Index backed by 200+ benchmark cases and real-pipeline fixtures.

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-000000?logo=next.js)](https://nextjs.org)
[![TypeScript](https://img.shields.io/badge/TypeScript-strict-3178C6?logo=typescript&logoColor=white)](https://typescriptlang.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Tests](https://img.shields.io/badge/tests-431%20passing-2ea44f)](#engineering-rigor)
[![Intelligence Index](https://img.shields.io/badge/Intelligence%20Index-97.3%2F100%20(A%2B)-7C3AED)](#the-self-grading-eval-platform)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**12 specialized agents · 5 LLM providers with circuit-breaker failover · deterministic mention counting · cross-community bias detection · vector memory · Google OAuth persistent identity · live zero-API re-ranking — all on free tiers.**

</div>

---

> Not a chatbot. Not a listing aggregator. ShopSense is a **research pipeline** that reads 15 Reddit threads and a handful of expert reviews, counts what real people actually recommend (with a deterministic automaton, not an LLM guess), checks whether communities *disagree*, scores everything against a rubric it built **for you** in an interview, and streams the whole thing to your browser live — then lets you re-weight your priorities and watch the ranking re-sort in under 5 milliseconds with zero additional API calls.

It is also one of the few projects of its kind that **measures its own decision quality** — not just with synthetic checks, but against **recorded real model output**. 200+ benchmark cases feeding a self-grading 9-metric Intelligence Index. A comprehensive benchmark suite plus replayed real-pipeline fixtures scores the system **97.3 / 100** and gates every commit in CI.

---

## Table of Contents

- [Why this is hard (and why most "AI shopping" tools are shallow)](#why-this-is-hard)
- [The end-to-end pipeline](#end-to-end-pipeline)
- [Engineering rigor — the part most projects skip](#engineering-rigor)
  - [The self-grading eval platform](#the-self-grading-eval-platform)
  - [Golden-file LLM-shape tests](#golden-file-llm-shape-tests)
  - [Reliability hardening](#reliability-hardening)
- [Deep dives into the smart parts](#deep-dives)
- [Tech stack](#tech-stack)
- [Quick start](#quick-start)
- [Project structure](#project-structure)
- [Design decisions worth knowing](#design-decisions-worth-knowing)

---

## Why this is hard

Every "best X" article is SEO bait. Reddit has the real signal, but reading 15 threads to extract one decision takes hours. AI chatbots hallucinate prices, recommend discontinued models, and hand the same generic answer to a marathon runner and a recording engineer.

The hard parts aren't "call an LLM." They are:

| Hard problem | Naive approach | What ShopSense does |
|---|---|---|
| **Counting recommendations** | Ask the LLM "how many mentioned this?" | **Aho-Corasick automaton** — deterministic O(n) match across every alias, span-deduplicated. Exact integers, auditable. |
| **Different users, different winners** | One generic ranking | **Per-user weighted rubric** built from an adaptive interview, with hard-constraint enforcement. |
| **Community disagreement** | Average the sentiment | **Cross-subreddit bias detection** — flags when r/audiophile and r/budgetaudiophile evaluate against different reference points. |
| **Free-tier rate limits** | Hit one provider until it 429s | **5-provider circuit-breaker failover** + a round-robin pool giving 4× effective throughput. |
| **Provider returns garbage JSON** | Crash, or silently corrupt | **Repair → validate → canonicalize** at every parse boundary, covered by **golden-file shape tests**. |
| **"Is the system actually good?"** | Vibes | A **157-scenario benchmark** with an Intelligence Index, wired into CI. |

---

## End-to-end pipeline

Every numbered stage is a real, separable step with its own failure handling. The annotations
under each one are the *smart moves* — the edge cases and optimizations that make the output
trustworthy rather than just plausible.

```
Query: "best wireless earbuds under ₹3000 for gym"
  │
  ├─ [0]  SEMANTIC CACHE CHECK ──────────────── embeddings + cosine ≥ 0.95
  │        reuse a recent near-identical search (same category/region/rubric) → skip everything
  │        miss → continue. exact md5 cache also checked (query|category|weights|Q&A)
  │
  ├─ [1]  CATEGORY DETECTION ────────────────── Groq Llama 70B + rule layer + LRU cache
  │        "earbuds" → electronics/earbuds · region from currency (₹ → india)
  │        ambiguity guard: "watch" → disambiguation prompt (analog/smart/fitness)
  │        path-traversal-safe slug sanitisation before any filesystem use
  │
  ├─ [2]  CRITERIA GENERATION ───────────────── Gemini (cached per category)
  │        7–12 product-SPECIFIC criteria (sound_signature, anc_effectiveness, fit_stability…)
  │        forbids generic names ("build_quality"); forces price_to_value + 1 hidden-expert axis
  │        every criterion must be interview-able · retry if <6 returned · hard fallback set
  │
  ├─ [3]  ADAPTIVE INTERVIEW ────────────────── Mistral Small (warm, conversational)
  │        budget first → use case → EVERY remaining criterion (full coverage, even minor ones)
  │        memory injection: skips questions answered in past searches
  │        message classifier: ANSWER / QUESTION / MIXED / SKIP / COMMAND / UNCLEAR
  │        → typed UserIntent {hard_constraints, budget, preferences, exclusions, uncertainties}
  │
  ├─ [4]  RUBRIC GENERATION ─────────────────── Gemini + gap-fill
  │        weight 0–10 per criterion, tied to what the user actually said
  │        hard constraints → 9–10 · exclusions → 1–2 · normalized to a 0–1 scale
  │        gap-fill: infers weights for any criterion still uncovered from research signal
  │        manual-weight restore: user's slider edits survive regeneration
  │
  ├─ [5]  PARALLEL RESEARCH ─────────────────── ThreadPoolExecutor
  │        ├─ REDDIT  ~15 threads · 5 query variants (region/budget/use-case/“vs”)
  │        │          comment-tree flatten (3 levels) · Jaccard dedup (>60% title overlap)
  │        └─ REVIEWS 6–8 sites · Gemini grounding (live Google) + YouTube transcripts
  │                   Jina Reader fallback for JS/403 pages · numeric authority scoring
  │                   time-bounded domain blacklist (status-code-aware, auto-rehabilitating)
  │
  ├─ [6]  PARALLEL SUMMARIZATION ────────────── Provider pool (Groq/Gemini/Mistral, 4× throughput)
  │        1 focused sub-agent per thread · 150K raw chars → 30K structured (80% compression)
  │        adaptive throttle on 429 · per-thread failure isolated (1 bad thread ≠ failed run)
  │
  ├─ [7]  MENTION COUNTING ──────────────────── Pure Python, NO LLM (deterministic)
  │        alias discovery (XM5 = Sony WF-1000XM5) → Aho-Corasick automaton, single O(n) pass
  │        span dedup: "Buds Air 7 Pro" suppresses nearby "Buds Air 7"
  │        distinct recommenders counted per comment (1 user × 10 posts ≠ 10 votes)
  │
  ├─ [8]  CROSS-SUBREDDIT VALIDATION ────────── Gemini
  │        compares sentiment across communities → consistent / split / single_source
  │        only fires when 2+ subreddits AND 3+ mentions (no LLM on low-signal data)
  │
  ├─ [9]  MAIN ANALYSIS ─────────────────────── Gemini 2.5 Flash (1M context)
  │        aggregates structured summaries + authority-weighted reviews → ranked product list
  │        separates materials (category types) from buyable products · budget enforcement
  │        output normalised/repaired (markdown-stripped, deduped, schema-coerced)
  │
  ├─ [10] SCORING (hybrid) ──────────────────── Groq, batched 3/call
  │        top candidates full LLM (0–10 per criterion + evidence quote) · tail heuristic
  │        hard-constraint override: a MUST violation is forced to 1–3 regardless of hype
  │        prompt-injection sanitiser strips instruction-override text from research
  │
  ├─ [11] TARGETED EVIDENCE ENRICHMENT ──────── Serper + Jina full-page read + 1 batched Gemini
  │        top products' highest-weight NO-DATA criteria → fetch the real fact, with source
  │        ≤6 searches + 1 LLM call · cached 7 days · flag-gated · cannot break the pipeline
  │        real run: top-5 went from mostly [NO DATA] → 6/6 sourced coverage
  │
  ├─ [12] MISSING-DATA FAIRNESS ─────────────── Pure Python (peer-mean imputation)
  │        whatever's still unfindable → peer mean, not a penalising 4/10
  │        so "best-documented" never beats "actually best" · attaches data_coverage + confidence
  │
  ├─ [13] FINAL ENRICHMENT ──────────────────── parallel
  │        real-time prices (Amazon/Flipkart via Serper) · validated buy-links (token-matched)
  │        pgvector memory lookup (k=5, cosine 0.7) · "why this fits you" per product
  │
  └─ [14] RESULTS UI ────────────────────────── live SSE stream
          ranked products · live sliders → instant re-rank (<5ms, ZERO API calls)
          per-product "% data-backed" confidence badge · compare mode · community badges
          diagnostics panel · CSV/PDF/share export
```

Every stage streams to the browser over **Server-Sent Events** with auto-reconnect, a 30-min
stall watchdog, and a cache-hit fast path. Stages 7, 12 and the live re-rank run **without any
LLM call** — deterministic by design, so the parts that decide the ranking are auditable.

---

## Engineering rigor

This is the section that separates ShopSense from a weekend LLM wrapper. The hard problem with agentic systems isn't writing the happy path — it's knowing whether the system is *good*, and keeping it good as models drift and providers misbehave.

### The self-grading eval platform

ShopSense ships a **pure-Python evaluation harness** (`evals/`) that scores the recommendation engine across **157 scenarios in 4 categories** (earbuds, laptops, headphones, monitors) and **21 expert-annotated judgments** — **zero API calls, ~0.1 seconds**. The **Intelligence Index is 97.3 / 100 (A+)**, a weighted composite of 9 metrics:

| Metric | What it proves | Score |
|---|---|---|
| `recommendation_quality` | The right product wins for each scenario | **100.0** |
| `counterfactual_sensitivity` | Changing one weight changes the winner as expected | **100.0** |
| `ranking_quality` | Rankings are internally consistent (no contradictions) | **100.0** |
| `robustness` | 15 prompt-injection / shill / token-flood attacks can't corrupt rankings | **100.0** |
| `retrieval_quality` | Real research carries praise, complaints, and community signal | **100.0** |
| `explanation_integrity` | Real evidence is grounded, not "no data found" placeholders | **100.0** |
| `semantic_consistency` | Paraphrased queries don't flip the #1 pick | **96.0** |
| `personalization_strength` | Different personas genuinely get different winners | **92.5** |
| `human_alignment` | Engine agrees with a cross-category expert panel | **76.9** |

> **The part that makes this real, not a vanity score:** `retrieval_quality` and `explanation_integrity` can only be judged against *actual model output*. Rather than fake them from synthetic data, ShopSense replays **recorded real-pipeline fixtures** — committed captures of real Reddit → real LLM analysis → real scored products — so these two metrics produce genuine scores in CI **deterministically and for free**. A separate `python -m evals.online.record` job (capped at 2 live queries for free-tier limits) refreshes those fixtures from the real pipeline. The Index therefore measures *both* scoring math **and** live AI output quality — and if a model update starts dropping products or emitting ungrounded evidence, CI fails loudly.

**Fully data-driven, zero hardcoding.** Categories are not Python files — they are JSON pools in `evals/data/pools/`. The framework code (`pool_loader.py`) contains **no product, category, or criterion names whatsoever**. Adding a brand-new benchmark category is a single JSON drop-in:

```jsonc
// evals/data/pools/cameras.json
{
  "category": "cameras",
  "criteria":  [ { "name": "image_quality", "label": "Image Quality" }, ... ],
  "products":  [ { "name": "...", "scores": { "image_quality": 9, ... } }, ... ],
  "scenarios": [ { "id": "...", "weights": {...}, "expected_rank_1": "..." }, ... ],
  "human_judgments": [ ... ]
}
```

**A validator keeps the benchmark honest.** `python -m evals.benchmarks.validate_pools` recomputes the deterministic winner for every scenario from the scoring engine and **fails if a hand-labeled winner disagrees** — catching authoring errors *in the test data itself* before they can silently drag down a metric. (It caught 13 of my own mistakes during development.) This runs in CI before the eval gate.

```bash
make validate-pools   # schema + referential integrity + winner consistency
make ci               # validate-pools → full test suite → Intelligence Index gate
```

The CI gate (`python -m evals ci`) fails the build if the index drops below 88, if any deterministic metric falls below a tightened per-metric floor (~10 pts under its current score), or if a >10-point regression is detected against history.

### Golden-file LLM-shape tests

Models change. Providers swap formats. The defense is a suite that feeds **deliberately malformed raw LLM strings** — markdown-wrapped JSON, missing keys, hallucinated criteria, out-of-range weights, non-numeric types, trailing commas, total garbage — through the **real parse boundaries** of `rubric`, `interview`, and `cross_validate`, and asserts each still emits a canonical, downstream-safe shape (or a clean fallback) and never crashes.

```
30 shape cases × (rubric · next-question · message-classifier · intent-extractor · cross-validate)
→ if a provider starts returning a new shape tomorrow, CI fails loudly instead of corrupting a ranking
```

Combined with golden tests for the scorer and normalizer, recorded-pipeline replay (extraction recall, evidence grounding, no-hallucination checks), and the semantic-cache policy suite, the project ships **431 tests** covering unit logic, DB round-trips, the API surface, pipeline orchestration, real-output replay, and these LLM-shape boundaries.

### Reliability hardening

A pass focused entirely on failure modes — the unglamorous work that makes a demo into a system. Highlights:

- **Provider-aware embedding cache.** Gemini (3072-dim) and Cohere (384-dim) vectors live in *incompatible* spaces. The cache now tags every vector with its provider, so a fallback can never silently compare a Gemini query against a Cohere memory. Legacy plain-list entries degrade gracefully as `provider="unknown"`.
- **Time-bounded domain blacklist.** Was: 3 failures → *permanent* ban (one rate-limit could blacklist Wired forever). Now: **status-code-aware scoring** (403/401 weigh heavily, 429/timeouts lightly) with **24h / 7d expiry** and **success-based rehabilitation** — and the disk write happens *outside* the lock so parallel workers don't block.
- **Source authority, rewritten.** Tiers became a **0–100 numeric score** with **category-specific adjustments** (RTINGS is gold for TVs, irrelevant for skincare), **international-TLD brand families** (`wired.co.uk` → trusted), **path inspection** (`forbes.com/advisor/…` is affiliate, not editorial), and a separate **source_type** so Reddit counts as *community evidence*, not an editorial authority.
- **Self-healing Postgres schema.** A legacy DB missing a column no longer crashes startup — the schema adds it defensively before any index references it.
- **Frontend resilience.** SSE **auto-reconnect with exponential backoff**, a 30-minute **stall watchdog**, **multi-tab checkpoint isolation**, **localStorage/sessionStorage quota safety with LRU eviction**, O(n) price merges (was O(n²)), and `next/dynamic` lazy-loading of heavy research components.
- **Parallelized + validated shopping links.** Per-retailer Serper lookups now run concurrently, and a candidate URL is **validated against the product's distinctive tokens** before it's accepted — so you never get a phone *case* when you searched for the phone.
- **Semantic query cache.** "Best gym earbuds" and "earbuds for working out" are the same intent. A query embedding is matched (cosine ≥ 0.95) against recent searches with the *same category, region, and rubric fingerprint* — a hit reuses the prior result and skips the entire ~85s research run. Safe by construction: a different rubric never produces a hit, so you never see results scored against someone else's priorities.
- **Targeted evidence enrichment (gets the real fact, not an estimate).** After scoring, the top products' highest-weight criteria that came back with *no* research evidence trigger a focused fetch — one Serper query per product (parallel, cached 7 days) **plus a full-page read of the top result via Jina Reader** for the depth 30-word snippets miss (exact specs, tested figures), then a *single* batched LLM extraction that returns a score only when the source actually supports it, with the **source domain cited**. On a real `"best smartphone under 20000"` run this lifted the top 5 from mostly-`[NO DATA]` to **6/6 real data coverage**. Lean (≤6 searches + 1 LLM call), flag-gated, page reads degrade gracefully when a site blocks them, and the whole stage is wrapped so it can never break the pipeline.
- **Missing-data fairness (the ranking trust fix).** Whatever evidence enrichment still can't find is imputed to the **peer mean** (the average score of products that *do* have evidence on that criterion) rather than a penalising 4/10 — so the *best-documented* product never out-ranks a genuinely-better one, and a thin-data product can't leapfrog on one lucky data point. Every result carries `data_coverage` (0–1) and a `confidence` band so any consumer can see how well-evidenced a ranking is.
- **Versioned database migrations.** Schema changes are tracked through **three Alembic migrations**: a baseline that creates all original tables with `CREATE TABLE IF NOT EXISTS` (idempotent on any existing database), a second that adds `user_id` columns to `Search` and `Profile` with `server_default='__legacy__'` so no existing row is touched, and a third that creates the `EmbeddingCache` table with a 1-year TTL column and an expiry index. On startup, `env.py` probes Postgres with a 3-second timeout and silently falls back to SQLite if it is unreachable — so a misconfigured `POSTGRES_URL` produces a warning, not a crash.
- **2-tier embedding cache.** Computing a `text-embedding-004` vector for every unique query adds latency and burns free-tier quota. A **2-tier cache** hits an in-memory dict first (sub-microsecond, process-lifetime), then an `EmbeddingCache` DB table (1-year TTL, LRU eviction at 1 million rows). Both tiers are tagged with the provider name, so a Gemini (3072-dim) vector can never be compared against a cached Cohere (384-dim) vector in a silent dimension mismatch. A 24-hour background coroutine purges expired rows to keep the table bounded without manual intervention.
- **Per-user rate limiting.** `slowapi` already enforced per-IP buckets (10/min on search, 200/min globally). The key function now promotes **authenticated users to per-`user_id` buckets** while keeping guests on per-IP — so a shared egress IP (office, campus Wi-Fi) no longer penalises unrelated users. Auth and guest traffic are always counted independently.
- **Google OAuth with zero-downtime guest session adoption.** `NextAuth v5` (Google OAuth, JWT strategy, 30-day sessions) gates the `/memory/*` routes — search, interview, and the full pipeline remain fully public. When a user logs in for the first time an `AdoptLegacy` component fires once silently in the browser: it calls `POST /api/auth/adopt-legacy` with the old `ss_*` guest session ID, and the backend re-assigns all `UserSignal`, `ProductMemory`, `Search`, and `Profile` rows to the new `auth_*` account. Preferences and history built as a guest surface immediately under the authenticated identity, on every device, with no user action required.

---

## Deep dives

### 12 specialized agents

Each agent is tuned to its task — its own provider, temperature, and prompt strategy.

| Agent | Primary Provider | Temp | Task |
|---|---|---|---|
| `category_detector` | Groq Llama 70B | 0.1 | Query classification + region detection |
| `criteria_generator` | Gemini 2.5 Flash | 0.3 | 6–10 buying criteria per category |
| `interview_questioner` | Mistral Small | 0.7 | Conversational questions covering every rubric criterion |
| `interview_classifier` | Groq Llama 70B | 0.1 | Classify message: ANSWER/QUESTION/MIXED/SKIP/COMMAND/UNCLEAR |
| `preference_summarizer` | Groq Llama 70B | 0.3 | Extract structured UserIntent from Q&A |
| `rubric_generator` | Gemini 2.5 Flash | 0.2 | Weighted scorecard from criteria + profile |
| `gap_filler` | Gemini 2.5 Flash | 0.2 | Infer weights for uncovered criteria |
| `thread_summarizer` | **Pool** (Groq/Gemini/Mistral) | 0.2 | One Reddit thread → structured data |
| `main_analyzer` | Gemini 2.5 Flash | 0.2 | Aggregate summaries + reviews → product list |
| `product_scorer` | Groq Llama 70B | 0.1 | Score 0–10 per criterion with evidence |
| `explanation_writer` | Groq Llama 70B | 0.5 | "Why this product fits you" |
| `cross_validator` | Gemini 2.5 Flash | 0.1 | Explain community sentiment disagreement |

### 5-provider circuit-breaker failover

All five run on **free tiers**. No paid API required.

```
Groq (llama-3.3-70b)  →  Cerebras (llama-3.1-8b)  →  Gemini 2.5 Flash  →  Mistral Small  →  OpenRouter
  fastest, primary         ultra-fast, 1 try          1M ctx, big payloads   conversational     master fallback
```

- **Circuit breaker** — rolling-window failure rate trips a provider; 429/502/503 → 60–120s cooldown; 401/403 → marked session-dead for the run.
- **In-flight dedup** — N parallel callers requesting the same embedding/completion collapse to one request; the rest wait on an Event and reuse the result.
- **Provider-aware token budgets** — research windows resize per active provider's context limit before each call.
- **Round-robin pool** — `thread_summarizer` cycles across providers for ~4× effective rate limit, thread-safe.

### Aho-Corasick mention counting

LLM mention counts are estimates that conflate `XM5` / `Sony XM5` / `WF-1000XM5` and hallucinate under pressure. ShopSense uses a deterministic automaton instead:

1. **Alias discovery** — per-thread LLM call finds every name a product was called.
2. **Automaton build** — all names + aliases compiled into one Aho-Corasick multi-pattern matcher; a single O(n) pass over the corpus.
3. **Span dedup** — at overlapping positions the longer match wins; `"Buds Air 7 Pro"` suppresses a nearby `"Buds Air 7"` within a 30-char window.

Result: **exact integers**, with *distinct recommenders* counted per comment (one enthusiast posting 10 times ≠ 10 recommenders).

### Structured UserIntent

The interview produces a typed object, not a text blob, so every downstream stage reads fields directly:

```python
UserIntent = {
  "hard_constraints": ["must be under 30g", "no in-ear style"],
  "budget":           "under ₹3000",
  "preferences":      ["bass-heavy", "good for gym", "long battery"],
  "exclusions":       ["no open-back"],
  "uncertainties":    ["maybe ANC if in budget"],
}
```

`rubric_generator` weights constraints to 9–10 and exclusions to 1–2 · `main_analyzer` injects a structured override block · `product_scorer` forces a 1–3 score on any MUST violation regardless of evidence.

### Live re-ranking — zero API calls

The full rubric and per-product scores load into the browser once. Dragging a weight slider recomputes `Σ(score × weight) / Σ weight` across all products in **<5ms**, animated with Framer Motion spring physics. Explore *"what if battery mattered more?"* instantly — no server contact, no cost.

### Vector memory across searches

Durable signals ("has sensitive ears", "commutes 2h daily", "never buys open-back") are embedded and stored; transient context (this search's budget) never is. Retrieval is **pgvector cosine similarity** (`k=5`, threshold `0.7`), cross-category-filtered, and used by the interviewer to **skip questions you've already answered** in past searches. Embedding chain: Gemini `text-embedding-004` → Cohere → HuggingFace → local `sentence-transformers`.

---

## Tech stack

**Backend** — Python 3.11+ · FastAPI · Uvicorn · PostgreSQL 16 + pgvector (prod) / SQLite (dev) · Server-Sent Events · `ThreadPoolExecutor` (no async overhead) · `pyahocorasick` · BeautifulSoup + Jina Reader fallback · slowapi rate limiting.

**Frontend** — Next.js 16 (App Router) · TypeScript strict · Tailwind CSS v4 · shadcn/ui (75 components) · Framer Motion · Zustand + SWR · `cmdk` ⌘K palette · `recharts` · NextAuth v5 (Google OAuth, JWT, 30-day sessions).

**LLM providers (all free tier)** — Groq · Cerebras · Google Gemini · Mistral · OpenRouter.

**External APIs** — Gemini grounding (review discovery) · Serper (2500/mo free) · PRAW (optional deep Reddit) · Gemini Embeddings.

---

## Quick start

**Prerequisites:** Python 3.11+, Node 18+, and at least one free key (Groq or Gemini).

```bash
git clone https://github.com/Om-5640/shopsense.git
cd shopsense
cp .env.example .env        # add GEMINI_API_KEY / GROQ_API_KEY / SERPER_API_KEY / OPENROUTER_API_KEY
```

Authentication is optional for local use — search and interview work without any auth credentials. To enable Google OAuth and persistent cross-device memory:

```bash
# generate a signing secret
openssl rand -base64 32   # → paste as NEXTAUTH_SECRET in web/.env.local

# add Google OAuth credentials (Google Cloud Console → APIs & Services → Credentials)
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
NEXTAUTH_URL=http://localhost:3000
```

**API**

```bash
cd api
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

**UI**

```bash
cd web
cp .env.example .env.local
pnpm install && pnpm dev        # http://localhost:3000
```

**CLI**

```bash
python run.py "best earbuds under ₹3000"
python run.py "best mechanical keyboard" --no-reviews
python run.py "best budget laptop" --output results.json --scoring-mode llm
```

**Postgres + pgvector (production)**

```bash
docker-compose up -d            # Postgres on 5433, pgvector enabled
```

**Run the eval platform**

```bash
make eval                    # golden-file + shape + recorded-replay tests (~1s, no keys)
make validate-pools          # benchmark data integrity
python -m evals full         # full Intelligence Index report across all categories
python -m evals.online.record  # capture fresh real-pipeline fixtures (2 live queries)
```

---

## Project structure

```
shopsense/
├── api/
│   ├── main.py              REST + SSE endpoints, per-user/per-IP rate limiting, JWT auth, sessions
│   ├── db.py                Dual-backend ORM (SQLite / Postgres + pgvector), 2-tier embedding cache, self-healing schema
│   ├── alembic/             3 versioned migrations: baseline → user_id columns → EmbeddingCache table
│   └── pipeline_runner.py   Orchestration, SSE event queue, stage timing, cache fast-path
│
├── web/                     Next.js 16 · 75 components · live re-ranking · SSE auto-reconnect
│   ├── auth.ts              NextAuth v5 config (Google OAuth, JWT callbacks, 30-day sessions)
│   ├── middleware.ts         Protects /memory/* routes in Next.js edge middleware
│   ├── app/login/           Google sign-in page
│   └── components/auth/     UserMenu avatar dropdown · AdoptLegacy (silent guest-to-auth migration)
│
├── evals/                   ◀ the self-grading platform
│   ├── data/pools/*.json            data-driven category benchmarks (zero hardcoding in code)
│   ├── data/fixtures/recorded/*.json recorded real-pipeline output, replayed free in CI
│   ├── benchmarks/          pool_loader · validate_pools · recorded · adversarial/semantic sets
│   ├── metrics/             9 metrics; online-only metrics fed by recorded fixtures
│   ├── online/record.py     capture real fixtures from 2 live queries (rate-limit aware)
│   ├── engine.py            pure-Python scoring mirror (no production imports)
│   ├── index.py             Intelligence Index composite
│   └── runner.py / cli.py   quick/full/ci/tournament/history
│
├── semantic_cache.py        near-duplicate-query reuse (embed → cosine ≥ 0.95)
│
├── agents.py                Agent registry, fallback chains, provider pool
├── llm_clients.py           5-provider facade, circuit breaker, in-flight dedup
├── interview.py             Adaptive interview, coverage termination, UserIntent
├── rubric.py · criteria.py  Personalized weighted scorecard + gap-fill
├── scorer.py                3-mode scoring + peer-mean missing-data fairness + confidence
├── evidence_enricher.py     targeted fetch: fills top-product NO-DATA gaps with sourced facts
├── thread_summarizer.py     Parallel sub-agent summarization
├── mention_counter.py       Aho-Corasick automaton + span dedup
├── alias_resolver.py        Per-thread alias discovery
├── cross_validate.py        Cross-subreddit bias detection
├── memory.py · embeddings.py  pgvector memory + provider-aware multi-fallback embeddings
├── reddit_fetch.py · review_fetch.py   multi-variant research + grounding + YouTube transcripts
├── source_filter.py         numeric authority scores, category-aware, source types
├── domain_blacklist.py      time-bounded, status-code-aware auto-blacklist
├── shopping_links.py · price_fetcher.py   validated links + real-time prices
└── tests/                   431 tests: unit · integration · e2e · golden-file · LLM-shape · embeddings
```

---

## Design decisions worth knowing

**Why an eval harness at all?** Because "it felt good in the demo" is not a quality bar. A 157-scenario benchmark with a CI gate turns *recommendation quality* into a number that can regress a PR — the same way a test suite turns *correctness* into one.

**Why data-driven JSON pools instead of Python fixtures?** So the framework generalizes to any category without code changes, and so the benchmark can't quietly encode product-specific assumptions in the engine. A validator proves each scenario's labeled winner matches the deterministic math.

**Why skip online-only metrics offline instead of approximating them?** An approximation that looks like a score is worse than an honest gap — it inflates the headline number with something that doesn't measure what it claims. Skipping keeps the index meaningful.

**Why Aho-Corasick instead of asking the LLM to count?** Determinism. Exact, auditable integer counts beat estimates that conflate aliases and hallucinate under load.

**Why structured UserIntent instead of flat text?** Every stage acts differently on hard constraints vs. soft preferences vs. exclusions. A typed dict makes constraint enforcement explicit and reliable; a text blob forces every consumer to re-parse.

**Why parallel summarization instead of one big call?** Focused context extracts better. One model reading a single 10K-char thread finds products more accurately than one reading 150K chars — and parallelism bounds wall time by the slowest thread, not the sum.

**Why hybrid scoring instead of always-LLM?** Users care about the top results, not whether #18 scored 4.2 or 4.4. LLM rigor where it matters, fast heuristics where it doesn't — 45s instead of 120s.

**Why ThreadPoolExecutor, not async?** Simpler, debuggable, sufficient for an I/O-bound profile. Rate limiting belongs at the provider layer, not the concurrency layer.

**Why Google OAuth only (no password / magic link)?** Eliminating password storage and email deliverability removes two entire attack surfaces and two external dependencies for an MVP. OAuth lets the identity provider handle credential security while the app focuses on its actual hard problem. Adding additional providers later is a one-line change in `auth.ts`.

**Why `__legacy__` as the server default for `user_id`, not `NULL` or `guest`?** `NULL` would break queries that filter by `user_id` without an `IS NULL` guard. `guest` implies a generic shared identity. `__legacy__` is self-documenting: it marks rows that existed before auth was introduced and that a user can *claim* via the adopt-legacy flow — distinct from any real session ID, and easy to filter in migrations and reporting scripts.

**Why a 2-tier embedding cache (memory + DB) instead of Redis?** The memory tier is sub-microsecond and zero-dependency. The DB tier survives restarts and shares the same SQLite/Postgres instance the rest of the schema already uses — no second infrastructure component to deploy, monitor, or pay for. At the expected query volume (hundreds/day, not millions) this is sufficient; Redis would be the right upgrade only if embedding throughput became the bottleneck.

**Why Alembic migrations instead of schema auto-detection?** Auto-detection (checking columns at startup and adding them) is fragile across environments and hides the actual schema history. Explicit versioned migrations give a clear audit trail, make CI validation straightforward (upgrade → downgrade → upgrade roundtrip), and allow `server_default` values that are impossible to express in a silent `ALTER TABLE` check.

---

## License

MIT — see [LICENSE](LICENSE).
