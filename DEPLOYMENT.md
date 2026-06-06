# ShopSense — Deployment Guide

## Quick Reference

| | Command |
|-|---------|
| Run backend | `cd api && uvicorn main:app --reload --port 8000` |
| Run frontend | `cd web && npm run dev` |
| Run migrations | `cd api && alembic upgrade head` |
| Run tests | `pytest tests/ -v` |
| Run evals | `python -m evals ci` |
| Check CI status | `gh run list --limit 5` |

---

## Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| Python | 3.11+ | `python --version` |
| Node.js | 20+ | `node --version` |
| pnpm | 9+ | `pnpm --version` |
| Git | any | `git --version` |
| Docker (optional) | 24+ | `docker --version` |

---

## Step 1 — Clone and Install

```bash
git clone https://github.com/Om-5640/shopsense.git
cd shopsense

# Backend
cd api
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Frontend
cd ../web
pnpm install
```

---

## Step 2 — Environment Variables

Copy the example files:
```bash
cp .env.example .env         # root-level (backend reads this)
cp web/.env.example web/.env
```

### Minimum Required (app runs without auth)

Edit `.env`:
```env
GEMINI_API_KEY=<your-key>       # https://aistudio.google.com — free tier
SERPER_API_KEY=<your-key>       # https://serper.dev — 2500 free searches/month
```

Edit `web/.env`:
```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

With just these two keys, the full pipeline runs. Google OAuth will not work yet — that requires Step 3.

### Recommended Additional Keys

```env
# .env (backend)

# LLM providers — more keys = faster + more resilient
GROQ_API_KEY=          # https://console.groq.com — free, fastest scoring
OPENROUTER_API_KEY=    # https://openrouter.ai — free tier, master fallback
MISTRAL_API_KEY=       # https://console.mistral.ai — free tier, interview questions
CEREBRAS_API_KEY=      # https://cloud.cerebras.ai — free tier, thread summarization
```

### All Environment Variables

#### Backend (`.env` in project root)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GEMINI_API_KEY` | **Yes** | — | Google Generative AI (Gemini 2.0 Flash) — main LLM and embeddings |
| `SERPER_API_KEY` | **Yes** | — | Google search API — Reddit URL discovery and pricing |
| `GROQ_API_KEY` | Rec. | — | Groq llama-3.3-70b — fast product scoring |
| `OPENROUTER_API_KEY` | Rec. | — | OpenRouter — master LLM fallback |
| `MISTRAL_API_KEY` | Opt. | — | Mistral Small — interview question generation |
| `CEREBRAS_API_KEY` | Opt. | — | Cerebras llama-3.1-8b — parallel thread summaries |
| `COHERE_API_KEY` | Opt. | — | Cohere embed-english-v3.0 — embedding fallback |
| `HF_API_KEY` | Opt. | — | HuggingFace Inference API — embedding fallback |
| `NEXTAUTH_SECRET` | Auth | — | JWT signing secret — must match frontend. Generate: `openssl rand -base64 32` |
| `USE_PRAW` | Opt. | `false` | Enable deep Reddit via PRAW (200–300 comments/thread) |
| `REDDIT_CLIENT_ID` | Opt. | — | PRAW OAuth app client ID |
| `REDDIT_CLIENT_SECRET` | Opt. | — | PRAW OAuth app secret |
| `REDDIT_USER_AGENT` | Opt. | — | PRAW user agent string, e.g. `ShopSense/1.0` |
| `YOUTUBE_API_KEY` | Opt. | — | YouTube Data API v3 — better video review discovery |
| `AMAZON_AFFILIATE_TAG` | Opt. | — | Amazon Associate tag — appended to buy links |
| `POSTGRES_URL` | Opt. | SQLite | Full connection string: `postgresql://user:pass@host:5432/db` |
| `PG_POOL_MIN` | Opt. | `1` | PostgreSQL connection pool minimum |
| `PG_POOL_MAX` | Opt. | `10` | PostgreSQL connection pool maximum |
| `CORS_ORIGINS` | Opt. | `http://localhost:3000` | Comma-separated allowed frontend origins |
| `SCORING_MODE` | Opt. | `hybrid` | `fast` (heuristic only), `hybrid` (LLM top-10), `llm` (all LLM) |
| `API_SECRET_KEY` | Opt. | — | Require this key on all endpoints — set in production |
| `REQUEST_TIMEOUT_S` | Opt. | `120` | Per-request timeout in seconds (SSE excluded) |
| `SESSION_CLEANUP_INTERVAL_S` | Opt. | `1800` | How often to clean stale pipeline sessions (seconds) |
| `SIGNAL_SCAN_LIMIT` | Opt. | `10000` | Max SQLite rows scanned for cosine similarity |
| `ALEMBIC_DATABASE_URL` | Opt. | auto | Override Alembic DB URL — suppresses Postgres probe warning |

#### Frontend (`web/.env`)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NEXT_PUBLIC_API_URL` | **Yes** | `http://localhost:8000` | Backend API base URL |
| `DATABASE_URL` | Opt. | `file:./prisma/shopping.db` | Prisma DB URL (only if using Prisma features) |
| `NEXTAUTH_SECRET` | Auth | — | Same value as backend `NEXTAUTH_SECRET` |
| `NEXTAUTH_URL` | Auth | `http://localhost:3000` | Full URL of the frontend app |
| `GOOGLE_CLIENT_ID` | Auth | — | Google OAuth 2.0 client ID |
| `GOOGLE_CLIENT_SECRET` | Auth | — | Google OAuth 2.0 client secret |

---

## Step 3 — Google OAuth Setup (Optional)

Skip this step if you only need guest mode (no login, no cross-device memory).

### 3a — Generate NEXTAUTH_SECRET

```bash
openssl rand -base64 32
# Example output: k8mFpQ2xL9vRnT4wYjZ7bDcH1eGiNsU0
```

Add to both `.env` and `web/.env`:
```env
NEXTAUTH_SECRET=k8mFpQ2xL9vRnT4wYjZ7bDcH1eGiNsU0
```

### 3b — Create Google OAuth Credentials

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (or select existing)
3. Navigate to **APIs & Services → Credentials**
4. Click **Create Credentials → OAuth 2.0 Client ID**
5. Application type: **Web application**
6. Name: `ShopSense` (or anything)
7. Under **Authorized redirect URIs**, add:
   - Local: `http://localhost:3000/api/auth/callback/google`
   - Production: `https://yourdomain.com/api/auth/callback/google`
8. Click **Create** — copy the **Client ID** and **Client Secret**

### 3c — Add Credentials to web/.env

```env
NEXTAUTH_URL=http://localhost:3000
GOOGLE_CLIENT_ID=123456789-abcdefg.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-abcdefghijklmnop
```

### 3d — Enable Google+ API (or People API)

In Google Cloud Console:
- **APIs & Services → Library**
- Search for "Google+ API" or "Google People API"
- Click **Enable**

---

## Step 4 — Database Setup

The backend auto-creates the SQLite database on first start. For a clean versioned setup, run migrations first:

```bash
cd api
alembic upgrade head
```

Expected output:
```
INFO  [alembic.runtime.migration] Running upgrade  -> 0001, Baseline
INFO  [alembic.runtime.migration] Running upgrade 0001 -> 0002, Add user_id columns
INFO  [alembic.runtime.migration] Running upgrade 0002 -> 0003, Add EmbeddingCache table
```

Check current state:
```bash
alembic current   # shows current revision
alembic history   # shows full migration chain
```

For **PostgreSQL** instead of SQLite:

```bash
# 1. Start Postgres (Docker)
docker-compose up -d postgres

# 2. Add to .env
POSTGRES_URL=postgresql://shopping:shopping@localhost:5433/shopping_agent

# 3. Run migrations
cd api && alembic upgrade head
```

---

## Step 5 — Start the App

```bash
# Terminal 1 — Backend
cd api
source venv/bin/activate
uvicorn main:app --reload --port 8000

# Terminal 2 — Frontend
cd web
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

**Verify it works:**
- Home page loads
- Try a search query (e.g. "best wireless earbuds under ₹3000")
- Results stream in via SSE
- If OAuth configured: click Sign In → Google login works

---

## Step 6 — Run Tests

```bash
# All tests
pytest tests/ -v

# Individual suites
pytest tests/unit/ -v          # 188 tests — embeddings, scorer, etc.
pytest tests/integration/ -v   # 53 tests — DB layer, pipeline runner
pytest tests/e2e/ -v           # 20 tests — API endpoints
pytest tests/evals/ -v         # 92 tests — golden-file regression

# Intelligence eval (CI gate)
python -m evals ci             # should score ≥ 97/100
```

---

## Docker Setup (PostgreSQL + pgvector)

The included `docker-compose.yml` starts a local PostgreSQL with pgvector:

```bash
# Start Postgres
docker-compose up -d postgres

# Verify it's healthy
docker-compose ps
# postgres   Up (healthy)

# Set connection string
# Add to .env:
POSTGRES_URL=postgresql://shopping:shopping@localhost:5433/shopping_agent

# Run migrations
cd api && alembic upgrade head

# Start backend and frontend normally (see Step 5)
```

To stop:
```bash
docker-compose down           # stops containers, keeps data
docker-compose down -v        # stops containers and deletes data
```

---

## Production Deployment

### Option A — Vercel (Frontend) + Railway (Backend)

**Frontend on Vercel:**

1. Push to GitHub (already done)
2. Go to [vercel.com](https://vercel.com) → Import repository
3. Set root directory to `web`
4. Add environment variables in Vercel dashboard:
   ```
   NEXT_PUBLIC_API_URL=https://your-backend.railway.app
   NEXTAUTH_SECRET=<your-secret>
   NEXTAUTH_URL=https://your-app.vercel.app
   GOOGLE_CLIENT_ID=<your-client-id>
   GOOGLE_CLIENT_SECRET=<your-client-secret>
   ```
5. Deploy — Vercel auto-deploys on every push to master

**Backend on Railway:**

1. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
2. Select the repository, set root directory to `api`
3. Set start command: `alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Add environment variables:
   ```
   GEMINI_API_KEY=...
   SERPER_API_KEY=...
   GROQ_API_KEY=...
   NEXTAUTH_SECRET=<same-secret-as-frontend>
   CORS_ORIGINS=https://your-app.vercel.app
   API_SECRET_KEY=<strong-random-string>
   ```
5. Add a PostgreSQL plugin in Railway — it auto-sets `POSTGRES_URL`

**Update Google OAuth redirect URI:**
Go back to Google Cloud Console → Credentials → your OAuth app → add:
```
https://your-app.vercel.app/api/auth/callback/google
```

### Option B — Docker Compose (Self-Hosted / VPS)

Create `docker-compose.prod.yml`:

```yaml
version: '3.8'
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: shopsense
      POSTGRES_USER: shopping
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "shopping", "-d", "shopsense"]
      interval: 10s
      retries: 5

  backend:
    image: python:3.11-slim
    working_dir: /app
    volumes:
      - .:/app
    command: >
      sh -c "pip install -r api/requirements.txt &&
             cd api && alembic upgrade head &&
             cd .. && uvicorn api.main:app --host 0.0.0.0 --port 8000"
    environment:
      POSTGRES_URL: postgresql://shopping:${DB_PASSWORD}@postgres:5432/shopsense
      GEMINI_API_KEY: ${GEMINI_API_KEY}
      SERPER_API_KEY: ${SERPER_API_KEY}
      NEXTAUTH_SECRET: ${NEXTAUTH_SECRET}
      CORS_ORIGINS: ${FRONTEND_URL}
      API_SECRET_KEY: ${API_SECRET_KEY}
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy

  frontend:
    image: node:20-alpine
    working_dir: /app/web
    volumes:
      - ./web:/app/web
    command: sh -c "npm install && npm run build && npm start"
    environment:
      NEXT_PUBLIC_API_URL: ${BACKEND_URL}
      NEXTAUTH_URL: ${FRONTEND_URL}
      NEXTAUTH_SECRET: ${NEXTAUTH_SECRET}
      GOOGLE_CLIENT_ID: ${GOOGLE_CLIENT_ID}
      GOOGLE_CLIENT_SECRET: ${GOOGLE_CLIENT_SECRET}
    ports:
      - "3000:3000"

volumes:
  postgres_data:
```

Deploy:
```bash
export DB_PASSWORD=<strong-password>
export GEMINI_API_KEY=...
export SERPER_API_KEY=...
export NEXTAUTH_SECRET=$(openssl rand -base64 32)
export FRONTEND_URL=https://yourdomain.com
export BACKEND_URL=https://api.yourdomain.com
export API_SECRET_KEY=$(openssl rand -base64 24)

docker-compose -f docker-compose.prod.yml up -d
docker-compose -f docker-compose.prod.yml logs -f
```

### Option C — Render.com

**Backend (Web Service):**
- Environment: Python 3.11
- Build command: `pip install -r api/requirements.txt`
- Start command: `cd api && alembic upgrade head && cd .. && uvicorn api.main:app --host 0.0.0.0 --port $PORT`
- Add all env vars in Render dashboard

**Frontend (Static Site or Web Service):**
- For static export: build command `cd web && pnpm install && pnpm build`, publish dir `web/out`
- For SSR: Node 20 web service, start command `cd web && pnpm start`

---

## Production Security Checklist

- [ ] `NEXTAUTH_SECRET` set to a cryptographically random 32+ char value
- [ ] `API_SECRET_KEY` set (protects all endpoints with API key auth)
- [ ] `CORS_ORIGINS` set to exact production frontend URL (not `*`)
- [ ] `POSTGRES_URL` uses a strong password, not default `shopping:shopping`
- [ ] Google OAuth redirect URIs updated to production domain
- [ ] `NEXTAUTH_URL` set to production frontend URL
- [ ] Backend not directly exposed — behind reverse proxy (nginx/Caddy/Railway)
- [ ] Logs do not print API keys (check via `docker-compose logs | grep -i key`)

---

## Health Checks

**Backend health:**
```bash
curl http://localhost:8000/api/health
# {"status":"ok","db":"sqlite","memory":{"signals":0,"products":0},"providers":{...}}
```

**Provider status:**
```bash
curl http://localhost:8000/api/providers/status
# Shows circuit breaker state for each LLM provider
```

**Migration status:**
```bash
cd api && alembic current
# Shows current revision (should be 0003)
```

**Test pipeline:**
```bash
curl -X POST http://localhost:8000/api/detect \
  -H "Content-Type: application/json" \
  -d '{"query": "best wireless earbuds"}'
# {"category":"earbuds","confidence":"high",...}
```

**Intelligence eval:**
```bash
python -m evals ci
# Should report ≥ 97/100
```

---

## Troubleshooting

### "POSTGRES_URL is set but unreachable — falling back to SQLite"

Postgres is in `.env` but not running. Either:
- Start Docker: `docker-compose up -d postgres`
- Or remove `POSTGRES_URL` from `.env` to use SQLite

### "no such table: Search" (during alembic upgrade)

```bash
cd api
alembic upgrade head
# Should run all 3 migrations cleanly
```

If it fails again, check `alembic current` and `alembic history` to see the state.

### "Module not found: next-auth"

```bash
cd web
pnpm install
# Or: npm install
```

### Google OAuth redirect_uri_mismatch

The redirect URI in Google Cloud Console must exactly match. For local:
```
http://localhost:3000/api/auth/callback/google
```

For production:
```
https://yourdomain.com/api/auth/callback/google
```

Check: Google Cloud Console → APIs & Services → Credentials → your OAuth client → Authorized redirect URIs.

### "JWT decode error" / 401 on API calls

Check that `NEXTAUTH_SECRET` in `.env` (backend) and `web/.env` (frontend) are **identical**.

```bash
grep NEXTAUTH_SECRET .env web/.env
# Both lines must have the same value
```

### "Too many requests" (429)

Default limits:
- `/api/search`: 10/min
- `/api/interview/*`: 60/min
- All other: 200/min

For development, temporarily raise in `api/main.py` or wait 1 minute.

### Import error: `import main` fails

```bash
cd api
python -c "import main"
# Read the full traceback — usually a missing package
pip install -r requirements.txt
```

### Frontend builds but shows blank page

```bash
cd web
npx tsc --noEmit    # check for TypeScript errors
npm run build       # check for build errors
```

Check `NEXT_PUBLIC_API_URL` in `web/.env` — must include `http://` and no trailing slash.

### Tests fail with "isolated_db" fixture error

The `conftest.py` fixture resets DB state. If tests are run outside `tests/` directory:
```bash
# Always run from project root
cd shopping-agent
pytest tests/ -v
```

---

## Database Operations

### Check migration state
```bash
cd api
alembic current    # current revision
alembic history    # full chain
```

### Roll back last migration
```bash
cd api
alembic downgrade -1    # one step back (e.g., 0003 → 0002)
```

### Roll back to baseline
```bash
cd api
alembic downgrade base  # WARNING: drops EmbeddingCache + user_id columns
```

### Run legacy data report
```bash
cd api
python migrate_legacy_users.py
# Reports how many rows have user_id='__legacy__' (pre-auth data)
```

### Adopt legacy guest data after user logs in
```bash
curl -X POST http://localhost:8000/api/auth/adopt-legacy \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"legacy_session_id": "ss_<old-session-hex>"}'
# {"merged": true, "from": "ss_...", "to": "auth_..."}
```

### Manual DB inspection
```bash
# SQLite
sqlite3 web/prisma/shopping.db
.tables
SELECT COUNT(*) FROM Search;
SELECT COUNT(*) FROM EmbeddingCache;

# PostgreSQL
psql $POSTGRES_URL
\dt
SELECT COUNT(*) FROM "Search";
```

---

## Updating the App

```bash
git pull origin master

# Backend: reinstall if requirements changed
cd api && pip install -r requirements.txt

# Run any new migrations
cd api && alembic upgrade head

# Frontend: reinstall if package.json changed
cd web && pnpm install

# Restart servers
```

---

## Common Commands Reference

```bash
# Start everything
cd api && uvicorn main:app --reload --port 8000 &
cd web && npm run dev &

# Tests
pytest tests/unit/ -v
pytest tests/integration/ -v
pytest tests/e2e/ -v
pytest tests/ -v --tb=short     # full suite, compact output

# Evals
python -m evals ci              # quick mode (~3 min)
python -m evals full            # full mode (~20 min)
python -m evals tournament      # A/B comparison mode

# DB
cd api && alembic upgrade head
cd api && alembic current
cd api && alembic history
cd api && python migrate_legacy_users.py

# CI
gh run list --limit 5
gh run view <run-id> --log-failed

# Clean up
docker-compose down             # stop Postgres
find . -name "*.pyc" -delete    # clean Python cache
cd web && rm -rf .next          # clean Next.js build cache
```
