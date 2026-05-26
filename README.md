# ShopSense — AI-Powered Personal Shopping Research

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-000000?logo=next.js)](https://nextjs.org)
[![TypeScript](https://img.shields.io/badge/TypeScript-strict-3178C6?logo=typescript&logoColor=white)](https://typescriptlang.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> Stop reading 50 Reddit threads. Get personalized buying recommendations from 15 Reddit threads + expert reviews, scored against what **you** specifically care about.

---

## What This Does (The Honest Version)

Most "best X" articles are SEO content farms. Reddit has real opinions but reading 15 threads to find one product takes hours.

**ShopSense does it for you.**

Type `"best earbuds under ₹3000"` → answer 8 questions about what matters to you → get a ranked list with real prices, evidence quotes from real users, and sliders to instantly re-rank if your priorities change.

```
User query: "best wireless earbuds under ₹3000"
     ↓
Category detection → earphones/wireless/budget-india
     ↓  
8-question interview → you care about: bass (high), comfort (high), mic quality (low)
     ↓
15 Reddit threads + 6 review sites fetched in parallel
     ↓
12 specialized AI agents analyze, summarize, score
     ↓
Results: 8 ranked products with prices, evidence, live sliders
     ↓  
Total wall time: ~85 seconds
```

---

## What Makes This Different

| Feature | ShopSense | Typical AI shopping tool |
|---|---|---|
| Data sources | 15 Reddit threads + 8 expert reviews | Product listings only |
| Personalization | 8-question interview → weighted rubric | None or basic filters |
| Re-ranking | Live sliders, zero API calls, <50ms | Re-query the LLM ($$$) |
| LLM providers | 5 providers, auto-failover | Single provider, hard fails |
| Pricing | Real Amazon/Flipkart scrape | "Check Google" |
| Memory | Cross-search preference learning | Session-only |
| Mentions | Community signal: X mentions, Y recommenders | Star ratings only |

### The Technical Highlights

**12 Specialized Agents, Each Tuned for Its Task**  
A `rubric_generator` runs at 0.3 temperature on Gemini (creative weights). A `product_scorer` runs at 0.1 on Groq (deterministic, fast). A `thread_summarizer` uses a pool of 4 providers cyclically for 4× the rate limit. Not one model doing everything — each agent is matched to the right provider and temperature.

**5-Provider Failover Chain**  
Groq → Cerebras → Gemini → Mistral → OpenRouter. Every agent has a fallback chain. If Groq rate-limits mid-run, the next call transparently moves to Cerebras. A circuit breaker trips a provider for 60–120 seconds after repeated failures, then auto-retries. Session-dead tracking marks providers that return 401/403 as permanently unavailable for that run.

**Hybrid Scoring: 100× Faster Than Pure LLM Ranking**  
`SCORING_MODE=fast` — pure heuristic (mention count × sentiment ratio × signal modifier). Instant.  
`SCORING_MODE=hybrid` — LLM scores only the top 10 products; the rest use fast heuristics.  
`SCORING_MODE=llm` — full LLM scoring for every product (highest quality, slowest).  
Default is `hybrid`. The math runs entirely in Python — no ML framework needed.

**Live Re-ranking With Zero API Calls**  
The full rubric + evidence is loaded into the browser. Dragging a slider triggers `rerank.ts` which recomputes the weighted sum across all products in <5ms. Products animate into new positions using Framer Motion spring physics. No server contact.

**Vector Memory That Learns Across Categories**  
Every interview answer is embedded and stored. "I have sensitive ears" from an earbuds search surfaces when you search headphones next month. Uses pgvector for production (cosine similarity at the DB layer) with in-memory fallback for SQLite. Embedding chain: Gemini → Cohere → HuggingFace → local `sentence-transformers`.

---

## Tech Stack

**Backend** — `api/` + root Python modules
- Python 3.11+, FastAPI, Uvicorn
- SQLite (default) / PostgreSQL + pgvector (production)
- Server-Sent Events for live pipeline streaming
- `ThreadPoolExecutor` for parallel agent calls
- No PyTorch, no heavy ML frameworks — pure Python math

**Frontend** — `web/`
- Next.js 16 (App Router) + TypeScript strict
- Tailwind CSS v4 + shadcn/ui (47 Radix-based components)
- Framer Motion for physics-based animations
- Zustand for client state, SWR for server cache
- `cmdk` for ⌘K command palette, `sonner` for toasts

**AI / LLM**
- 5 providers: Groq (llama-3.1-8b), Cerebras (llama-3.1-8b), Gemini (flash-1.5), Mistral (mistral-small), OpenRouter (llama-3.3-70b)
- All free tiers — no paid API required to run
- Embeddings: Gemini `text-embedding-004` (768-dim), with 3-provider fallback

---

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- At minimum: one free API key from [Groq](https://console.groq.com) **or** [Gemini](https://aistudio.google.com/apikey)

### 1. Clone and configure

```bash
git clone https://github.com/YOUR_USERNAME/shopsense.git
cd shopsense

# Copy the example env file and fill in your keys
cp .env.example .env
```

Edit `.env` — you need at minimum one LLM key and one search key:

```bash
GEMINI_API_KEY=AIza...       # free at aistudio.google.com
GROQ_API_KEY=gsk_...         # free at console.groq.com
SERPER_API_KEY=...           # free at serper.dev (2500 searches/mo)
OPENROUTER_API_KEY=sk-or-... # free at openrouter.ai (master fallback)
```

### 2. Start the API server

```bash
cd api
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### 3. Start the web UI

```bash
cd web
cp .env.example .env.local   # sets NEXT_PUBLIC_API_URL=http://localhost:8000
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

### 4. Or use the CLI directly

```bash
# From project root (pip install -r api/requirements.txt first)
python run.py "best face wash under 500"
python run.py "best mechanical keyboard" --no-reviews
python run.py "best blanket for winter" --skip-interview
python run.py "best earbuds under 3000" --output results.json
```

---

## Pipeline Walkthrough

```
┌─────────────────────────────────────────────────────────────────┐
│                        User Query                                │
│              "best earbuds under ₹3000 for gym"                  │
└──────────────────────┬──────────────────────────────────────────┘
                       │
          ┌────────────▼────────────┐
          │   1. Category Detect     │  groq → cerebras fallback
          │   earphones/wireless/    │  Outputs: category slug + region
          │   budget-india           │
          └────────────┬────────────┘
                       │
          ┌────────────▼────────────┐
          │   2. Interview (4-8 Qs) │  mistral (conversational)
          │   • "Bass or clarity?"  │  Builds: profile dict
          │   • "Daily commute?"    │  Saves to DB for reuse
          │   • "ANC important?"    │
          └────────────┬────────────┘
                       │
          ┌────────────▼────────────┐
          │   3. Rubric Generation  │  gemini
          │   Weighted scorecard    │  e.g. sound_quality: 0.35
          │   from profile          │       comfort: 0.28
          └────────────┬────────────┘
                       │
          ┌────────────▼────────────┐
          │   4. Research (parallel)│
          │   ├── 15 Reddit threads │  PRAW or Serper search
          │   │   fetched, 5 agents │  → thread_summarizer pool
          │   │   running in //     │
          │   └── 6-8 review sites  │  Wirecutter, RTINGS, etc.
          │       scraped via       │  domain blacklist skips 403s
          │       Gemini + Serper   │
          └────────────┬────────────┘
                       │
          ┌────────────▼────────────┐
          │   5. Main Analysis      │  gemini (1M context)
          │   Merges all summaries  │  Extracts: products, materials,
          │   Cross-validates       │  mention counts, complaints,
          │   subreddit signals     │  confidence labels
          └────────────┬────────────┘
                       │
          ┌────────────▼────────────┐
          │   6. Scoring            │  hybrid mode (default)
          │   Top 10: LLM score     │  groq (fast, parallel)
          │   Rest: heuristic score │  Outputs: 0-10 per criterion
          └────────────┬────────────┘
                       │
          ┌────────────▼────────────┐
          │   7. Enrichment         │
          │   ├── Price fetch       │  Amazon.in / Flipkart via Serper
          │   ├── Memory context    │  pgvector similarity search
          │   └── Explanation write │  "Why this fits you" per product
          └────────────┬────────────┘
                       │
          ┌────────────▼────────────┐
          │   Results Page          │
          │   Live sliders → rerank │  Pure JS, no API call
          │   ⌘K command palette   │  Jump to any product
          │   Compare mode          │  Side-by-side grid
          └─────────────────────────┘
```

---

## Pages

| Route | Description |
|---|---|
| `/` | Search home with recent history |
| `/research?q=` | Live pipeline with SSE progress stream |
| `/results/:id` | Ranked products, sliders, community data |
| `/compare?ids=` | Side-by-side product comparison grid |
| `/history` | All past searches, resumable |
| `/memory` | Your preference signals + product memories |
| `/settings` | Provider status, circuit breaker state |

---

## API Endpoints

Full reference in [ARCHITECTURE.md](ARCHITECTURE.md). Quick summary:

```
POST /api/search                → start pipeline, returns search_id
GET  /api/search/:id/stream    → SSE: live pipeline events
GET  /api/search/:id           → full result JSON
GET  /api/searches             → paginated history
POST /api/prices               → real-time price lookup
GET  /api/memory/context       → relevant signals for a query
GET  /api/providers/status     → per-provider health + circuit state
GET  /api/health               → liveness check
```

---

## Configuration

All options are in `.env`. See [.env.example](.env.example) for the full list with descriptions.

**Key toggles:**

| Variable | Default | Effect |
|---|---|---|
| `SCORING_MODE` | `hybrid` | `fast` (instant heuristic) / `hybrid` (LLM top 10) / `llm` (full LLM) |
| `USE_PRAW` | `false` | Enable PRAW for 200+ comments/thread (needs Reddit app credentials) |
| `POSTGRES_URL` | unset | Use PostgreSQL + pgvector instead of SQLite |

---

## Project Structure

```
shopsense/
├── api/
│   ├── main.py              21 REST + SSE endpoints
│   ├── db.py                SQLite/Postgres dual-backend ORM
│   └── pipeline_runner.py   Background thread + SSE event queue
│
├── web/                     Next.js 16 frontend
│   ├── app/                 App Router pages
│   ├── components/          47 Radix-backed UI components
│   └── lib/                 store.ts, api.ts, rerank.ts, hooks.ts
│
├── agents.py                Agent registry + provider round-robin
├── llm_clients.py           5-provider facade + circuit breaker
├── thread_summarizer.py     Parallel per-thread summarization
├── scorer.py                Hybrid deterministic + LLM scoring
├── memory.py                Cross-search personalization layer
├── embeddings.py            Multi-provider embedding service
├── price_fetcher.py         Real Amazon/Flipkart price scraping
├── reddit_fetch.py          Reddit thread fetcher (Serper + PRAW)
├── review_fetch.py          Review site scraper with category routing
├── domain_blacklist.py      Auto-blacklist for failing domains
├── cross_validate.py        Cross-subreddit bias detection
├── models.py                Central model config (swap models here)
└── run.py                   CLI orchestrator
```

---

## Extending the System

**Add a new LLM provider** — edit `agents.py`: add the provider to `_PROVIDER_FACTORIES`, add it to the fallback chain of any agent that should use it.

**Add a new region** — edit `review_fetch.py`: add the region to `_get_category_sites()`. Edit `price_fetcher.py`: add region-appropriate retailers.

**Add a new agent** — add an entry to `AGENTS` dict in `agents.py`, write your prompt, call `run_agent("your_agent_name", ...)`.

**Swap the default model** — edit `models.py`. One file, one change, all agents that use that provider pick it up.

---

## Roadmap

- [ ] Multi-user auth (currently single-user, `userId = "default"`)
- [ ] Postgres as default (currently SQLite default, Postgres opt-in)
- [ ] Export to PDF / shareable link
- [ ] Mobile-responsive UI polish
- [ ] Streaming token output on interview answers
- [ ] Agent-level observability dashboard
- [ ] Scheduled re-research ("alert me if prices drop")

---

## License

MIT — see [LICENSE](LICENSE).
