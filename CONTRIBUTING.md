# Contributing to ShopSense

Thanks for your interest in contributing.

---

## Dev Environment Setup

### Backend

```bash
git clone https://github.com/YOUR_USERNAME/shopsense.git
cd shopsense

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r api/requirements.txt

# Copy env and fill in at least one LLM key + SERPER_API_KEY
cp .env.example .env
```

Start the API server:
```bash
cd api
uvicorn main:app --reload --port 8000
```

### Frontend

```bash
cd web
pnpm install

# Create local env
cp .env.example .env.local   # then edit NEXT_PUBLIC_API_URL=http://localhost:8000

pnpm dev
```

---

## Running Tests

There is currently no automated test suite. Before submitting a PR, verify manually:

```bash
# 1. CLI smoke test
python run.py "best face wash under 500" --skip-interview --no-cache

# 2. API server starts
cd api && uvicorn main:app --port 8000

# 3. TypeScript check
cd web && npx tsc --noEmit

# 4. Lint
cd web && pnpm lint
```

If you're adding a significant feature, please add a test to `tests/` (create the directory if needed).

---

## Code Style

**Python**
- Follow PEP 8
- Use type hints for all function signatures
- Maximum line length: 110 characters
- Prefer `f-strings` over `str.format()`
- No bare `except:` — always catch specific exception types
- Comments only where the *why* is non-obvious

**TypeScript / React**
- Strict TypeScript — no `any` types
- No default exports except for Next.js pages (`export default function Page`)
- Components in `web/components/`, pages in `web/app/`
- Tailwind for all styling — no inline styles except dynamic values
- No comments explaining *what* code does — only *why*

---

## Making Changes

### Adding a New Agent

1. Add an entry to `AGENTS` dict in `agents.py`
2. Choose the best default provider for the task (see the existing choices for reference)
3. Always end the fallback chain with `"openrouter"` as the guaranteed fallback
4. Call it with `run_agent("your_agent_name", user_prompt=..., system=...)`

### Adding a New LLM Provider

1. Add a `_call_yourprovider(prompt, system, model, ...)` function in `llm_clients.py`
2. Add the provider to `_PROVIDER_FACTORIES` dict
3. Add `YOURPROVIDER_API_KEY` to `.env.example` with description
4. Add it to relevant agent fallback chains in `agents.py`

### Adding a New Region

1. `review_fetch.py` — add region-specific sites in `_get_category_sites()`
2. `price_fetcher.py` — add region-appropriate retailers and currency
3. `reddit_fetch.py` — optionally add region-specific subreddits to the query variants

### Adding a New Frontend Page

Pages live in `web/app/`. Use the App Router:
- Server components by default
- Add `'use client'` only when you need browser APIs, state, or event handlers
- Share state via `lib/store.ts` (Zustand) or URL params (nuqs)

---

## Pull Request Guidelines

1. **One feature / fix per PR** — makes review tractable
2. **Keep PRs small** — under 400 lines changed is ideal
3. **No secrets** — run `grep -rE "AIza|gsk_|sk-or-|csk-" .` before committing; output must be empty
4. **Update `.env.example`** if you add a new environment variable
5. **Update `CHANGELOG.md`** with a one-line entry under `[Unreleased]`

---

## Reporting Bugs

Open a GitHub issue with:
- What you searched for (can anonymize)
- Which stage failed (shown in the pipeline progress stream)
- The provider status at the time (`GET /api/providers/status`)
- Python version and OS

---

## Security

Never commit real API keys. If you accidentally do:
1. Immediately rotate the key at the provider dashboard
2. Force-push to remove it from git history (or ask a maintainer to do so)
3. The old key is compromised regardless of whether you delete the commit — rotate it
