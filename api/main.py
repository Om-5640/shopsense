"""
Shopping Research Agent v7 — FastAPI backend.

Endpoints:
  POST /api/detect               detect category + region from query
  POST /api/criteria             generate criteria for a category
  POST /api/interview/next       generate the next interview question (stateless)
  POST /api/interview/summarize  summarize Q&A into preferences text

  POST /api/search               start a new search (returns search_id immediately)
  GET  /api/search/{id}/stream   SSE stream of pipeline progress events
  GET  /api/search/{id}          full result once done
  GET  /api/searches             paginated history of all past searches

  GET  /api/profile/{category}   load saved profile for a category
  POST /api/profile/{category}   save profile for a category

  POST /api/prices               fetch real prices for a list of products

  GET  /api/memory/context       retrieve relevant signals for a query (pre-fills interview)
  GET  /api/memory/signals       list all user signals
  DELETE /api/memory/signals/{id} forget one signal
  GET  /api/memory/products      list all product memories
  POST /api/memory/products/{name}/status  update product status (bought, rejected, etc.)
  POST /api/memory/bought        record a purchase with optional feedback
  DELETE /api/memory/all         nuclear: wipe all memory

  GET  /api/health               provider status + DB health

Run with:
  cd api && uvicorn main:app --reload --port 8000
"""

import sys
import os
import json
import asyncio
import threading
import uuid
import time
from pathlib import Path
from typing import AsyncGenerator, Any, Optional
from contextlib import asynccontextmanager
import logging as _logging

try:
    import jwt as _jwt
    _HAS_PYJWT = True
except ImportError:
    _HAS_PYJWT = False

from fastapi import FastAPI, HTTPException, Query, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# ---------------------------------------------------------------------------
# Path setup — ensure api/ and project root are importable
# ---------------------------------------------------------------------------

_API_DIR = Path(__file__).parent
_ROOT = _API_DIR.parent
for _p in [str(_API_DIR), str(_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

_logger = _logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Core imports (must succeed at startup)
# ---------------------------------------------------------------------------

from db import init_db, create_search, update_search, get_search, list_searches
from db import get_profile, save_profile_db
from db import create_share_token, resolve_share_token
from db import reassign_user_data
from pipeline_runner import create_session, find_inflight_session, start_pipeline, get_session, cancel_session, cleanup_old_sessions

# ---------------------------------------------------------------------------
# Hot-path module imports — loaded at startup for faster per-request handling
# ---------------------------------------------------------------------------

from category import detect_category, _sanitize_slug
from reddit_fetch import detect_region, has_ambiguous_price
from criteria import generate_criteria
from interview import (
    generate_next_question,
    _identify_uncovered_criteria,
    MAX_QUESTIONS,
    MIN_QUESTIONS,
    _dynamic_coverage_target,
    process_message as _interview_process_message,
    _summarize_and_extract_intent,
)
from rubric import generate_rubric
from agents import get_provider_status
from memory import (
    find_relevant_signals,
    summarize_user_profile,
    list_user_signals,
    list_product_memories,
    save_product_memory,
    delete_signal,
    delete_product_memory,
    extract_and_save_signals,
    clear_all_memory,
)

try:
    from price_fetcher import fetch_prices as _fetch_prices
    _PRICE_FETCHER_AVAILABLE = True
except ImportError:
    _PRICE_FETCHER_AVAILABLE = False
    _logger.warning("[startup] price_fetcher not available — /api/prices will return 503")


# ---------------------------------------------------------------------------
# Environment config
# ---------------------------------------------------------------------------

_API_SECRET_KEY = os.environ.get("API_SECRET_KEY", "")

# Per-profile-key write lock — prevents two browser tabs (or rapid retries) from
# concurrently overwriting each other's profile saves for the same category.
_profile_write_locks: dict[str, threading.Lock] = {}
_profile_locks_mutex = threading.Lock()


def _get_profile_write_lock(key: str) -> threading.Lock:
    with _profile_locks_mutex:
        if key not in _profile_write_locks:
            _profile_write_locks[key] = threading.Lock()
        return _profile_write_locks[key]

# Session cleanup interval — default 30 min; reduce under high load or increase for quiet servers
_CLEANUP_INTERVAL_S = int(os.environ.get("SESSION_CLEANUP_INTERVAL_S", "1800"))

_CORS_ENV = os.environ.get("CORS_ORIGINS", "")
if not _CORS_ENV:
    _logger.warning(
        "[SEC-08] CORS_ORIGINS env var not set — defaulting to localhost:3000. "
        "Set CORS_ORIGINS to your production frontend URL(s) to prevent localhost CORS abuse."
    )
_CORS_ORIGINS = [
    o.strip()
    for o in (_CORS_ENV or "http://localhost:3000,http://127.0.0.1:3000").split(",")
    if o.strip()
]


# ---------------------------------------------------------------------------
# Session cleanup + lifespan
# ---------------------------------------------------------------------------

async def _session_cleanup_loop() -> None:
    while True:
        await asyncio.sleep(_CLEANUP_INTERVAL_S)
        try:
            # Run cleanup off the event-loop thread so acquiring _sessions_lock
            # doesn't block async request handlers (Bug L-3).
            removed = await asyncio.to_thread(cleanup_old_sessions)
            if removed:
                _logger.info("[session_cleanup] removed %d stale sessions", removed)
        except Exception as exc:
            _logger.warning("[session_cleanup] cleanup error: %s", exc)


async def _embedding_cache_cleanup_loop() -> None:
    """Purge expired EmbeddingCache rows once per day."""
    while True:
        await asyncio.sleep(24 * 3600)
        try:
            from db import purge_expired_embeddings
            deleted = await asyncio.to_thread(purge_expired_embeddings)
            if deleted:
                _logger.info("[embedding_cache_cleanup] purged %d expired rows", deleted)
        except Exception as exc:
            _logger.warning("[embedding_cache_cleanup] purge failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    if not _API_SECRET_KEY:
        _logger.warning(
            "[SEC] API_SECRET_KEY not set — authentication is DISABLED. "
            "Set API_SECRET_KEY before deploying to production."
        )
    init_db()
    try:
        import cache as _cache_mod
        _cache_mod.purge_expired(max_age_seconds=86400)
    except Exception as exc:
        _logger.debug("[startup] cache purge skipped: %s", exc)
    # Preload heavy pipeline modules now so the first real search request doesn't pay
    # the cold-import cost (~0.3-0.8s on spinning disk / slow SSD).
    # All imports are in try/except so a missing optional dep never prevents startup.
    _pipeline_preloads = [
        "scorer", "thread_summarizer", "mention_pipeline",
        "review_fetch", "normalizer", "embeddings",
    ]
    for _mod in _pipeline_preloads:
        try:
            __import__(_mod)
        except Exception as _exc:
            _logger.debug("[startup] preload skipped for %s: %s", _mod, _exc)
    cleanup_task = asyncio.create_task(_session_cleanup_loop())
    embedding_cleanup_task = asyncio.create_task(_embedding_cache_cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        embedding_cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        try:
            await embedding_cleanup_task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# Rate limiter + app
# ---------------------------------------------------------------------------

def _rate_limit_key(request: Request) -> str:
    """
    Auth users get per-user rate limits (independent buckets per account).
    Guests get per-IP limits (existing behaviour preserved).
    """
    auth_user = _verify_auth_token(request)
    if auth_user:
        return auth_user
    return get_remote_address(request)


limiter = Limiter(key_func=_rate_limit_key, default_limits=["200/minute"])

app = FastAPI(title="Shopping Research Agent v7", version="7.0.0", lifespan=lifespan)
app.state.limiter = limiter
@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Please try again shortly."},
        headers={"Retry-After": "60"},
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def timeout_middleware(request: Request, call_next):
    """Enforce a per-request timeout. SSE stream endpoints are excluded."""
    if "/stream" in request.url.path:
        return await call_next(request)
    timeout_s = int(os.environ.get("REQUEST_TIMEOUT_S", "120"))
    try:
        return await asyncio.wait_for(call_next(request), timeout=timeout_s)
    except asyncio.TimeoutError:
        return JSONResponse(status_code=504, content={"detail": "Request timed out"})


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response


# ---------------------------------------------------------------------------
# Auth + session helpers
# ---------------------------------------------------------------------------

def _check_api_key(request: Request) -> None:
    if not _API_SECRET_KEY:
        return  # auth disabled — development mode
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer ") and auth_header[len("Bearer "):] == _API_SECRET_KEY:
        return
    if request.headers.get("X-API-Key", "") == _API_SECRET_KEY:
        return
    raise HTTPException(status_code=401, detail="Invalid or missing API key")


def _get_session_user_id(request: Request) -> str:
    """
    Extract per-browser session ID from X-Session-ID header.
    Falls back to 'default' for backwards compatibility (CLI mode, old clients).
    Clients generate a UUID once and store it in localStorage — no auth required,
    just isolation so different browsers don't share memory/signals.
    """
    sid = request.headers.get("X-Session-ID", "").strip()
    if sid and len(sid) <= 64 and sid.replace("-", "").replace("_", "").isalnum():
        return sid
    return "default"


# ---------------------------------------------------------------------------
# JWT authentication (NextAuth v5 / Auth.js)
# ---------------------------------------------------------------------------

_NEXTAUTH_SECRET = os.environ.get("NEXTAUTH_SECRET", "").strip()


def _verify_auth_token(request: Request) -> Optional[str]:
    """
    Validates a NextAuth JWT from the Authorization: Bearer header.
    Returns 'auth_{sub}' on success, None for guest requests.

    Graceful degradation: if NEXTAUTH_SECRET is not configured, logs a warning
    and falls through to guest mode instead of crashing (Option A from the plan).
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:]
    if not _NEXTAUTH_SECRET:
        _logger.warning("[auth] NEXTAUTH_SECRET not set — treating request as guest")
        return None
    if not _HAS_PYJWT:
        _logger.warning("[auth] PyJWT not installed — treating request as guest")
        return None
    try:
        payload = _jwt.decode(token, _NEXTAUTH_SECRET, algorithms=["HS256"])
        sub = payload.get("sub")
        if not sub:
            raise HTTPException(status_code=401, detail="Token missing sub claim")
        return f"auth_{sub}"
    except _jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired — please log in again")
    except _jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")


def _get_user_id(request: Request) -> str:
    """
    Returns the effective user identifier for any request:
    - Authenticated: 'auth_{google_sub}' (from JWT)
    - Guest: session ID from X-Session-ID header (existing behaviour unchanged)
    """
    auth_user = _verify_auth_token(request)
    if auth_user:
        return auth_user
    return _get_session_user_id(request)


def _require_auth(request: Request) -> str:
    """FastAPI Depends() guard for endpoints that require a signed-in user."""
    uid = _get_user_id(request)
    if not uid.startswith("auth_"):
        raise HTTPException(status_code=401, detail="Please log in to access this resource")
    return uid


def _profile_key(user_id: str, category: str) -> str:
    """
    Namespace profile by user so different browsers don't overwrite each other.
    Returns bare category for legacy/CLI clients (user_id == 'default') so
    existing saved profiles remain accessible.
    """
    return f"{user_id}/{category}" if user_id != "default" else category


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class DetectRequest(BaseModel):
    query: str
    forced_category: Optional[str] = None


class CriteriaRequest(BaseModel):
    category: str


class InterviewNextRequest(BaseModel):
    category: str
    criteria: list[dict]
    qa_history: list[dict] = []
    memory_context: Optional[list[dict]] = None  # v7: pre-filled signals
    initial_query: str = ""
    primary_noun: str = ""


class InterviewSummarizeRequest(BaseModel):
    category: str
    qa_history: list[dict]


class ProcessMessageRequest(BaseModel):
    category: str
    criteria: list[dict]
    current_question: dict
    message: str
    qa_history: list[dict] = []


class SearchRequest(BaseModel):
    query: str
    category: str
    region: str = "global"
    profile: dict
    rubric: dict
    options: dict = {}
    qa_history: list[dict] = []  # v7: passed to signal extractor after pipeline
    primary_noun: str = ""       # v8: product type constraint for the analyzer


class SaveProfileRequest(BaseModel):
    profile: dict


class PricesRequest(BaseModel):
    products: list[str]
    region: str = "india"


class ProductStatusRequest(BaseModel):
    status: str  # "considered" | "rejected" | "purchased" | "returned"
    feedback: Optional[str] = None
    our_score: Optional[float] = None
    category: str = ""


class BoughtRequest(BaseModel):
    product_name: str
    category: str
    feedback: Optional[str] = None
    our_score: Optional[float] = None


# ---------------------------------------------------------------------------
# Category & criteria detection
# ---------------------------------------------------------------------------

@app.post("/api/detect")
@limiter.limit("30/minute")
def detect(request: Request, req: DetectRequest) -> dict:
    if req.forced_category:
        cat_info = {
            "category": _sanitize_slug(req.forced_category),
            "confidence": "high",
            "needs_disambiguation": False,
            "options": [],
        }
    else:
        cat_info = detect_category(req.query)

    region_detected = detect_region(req.query) or "global"
    needs_region_clarification = has_ambiguous_price(req.query) and region_detected == "global"

    return {
        **cat_info,
        "region": region_detected,
        "needs_region_clarification": needs_region_clarification,
    }


@app.post("/api/criteria")
def criteria(req: CriteriaRequest) -> dict:
    items = generate_criteria(req.category)
    return {"category": req.category, "criteria": items}


# ---------------------------------------------------------------------------
# Interview (stateless — client holds Q&A history)
# ---------------------------------------------------------------------------

@app.post("/api/interview/next")
def interview_next(req: InterviewNextRequest) -> dict:
    qa = req.qa_history
    force_continue = (len(qa) + 1) <= MIN_QUESTIONS

    if not force_continue:
        uncovered = _identify_uncovered_criteria(req.criteria, qa, req.initial_query)
        coverage = (len(req.criteria) - len(uncovered)) / max(len(req.criteria), 1)
        dyn_target = _dynamic_coverage_target(len(req.criteria))
        if coverage >= dyn_target or len(qa) >= MAX_QUESTIONS:
            return {"question": "", "why_asking": "", "targets_criterion": "", "is_done": True}

    result = generate_next_question(
        req.category,
        req.criteria,
        qa,
        initial_query=req.initial_query,
        memory_context=req.memory_context or [],
        primary_noun=req.primary_noun or "",
    )
    if force_continue:
        result["is_done"] = False
    return result


@app.post("/api/interview/process_message")
@limiter.limit("60/minute")
def process_message_endpoint(request: Request, req: ProcessMessageRequest) -> dict:
    return _interview_process_message(
        req.category, req.criteria, req.current_question, req.message, req.qa_history
    )


@app.post("/api/interview/summarize")
def interview_summarize(req: InterviewSummarizeRequest) -> dict:
    summary, intent = _summarize_and_extract_intent(req.category, req.qa_history)
    return {"preferences_summary": summary, "intent": intent}


# ---------------------------------------------------------------------------
# Rubric generation
# ---------------------------------------------------------------------------

@app.post("/api/rubric")
@limiter.limit("30/minute")
def generate_rubric_endpoint(request: Request, body: dict) -> dict:
    category = body.get("category", "")
    criteria = body.get("criteria", [])
    profile = body.get("profile", {})
    user_id = _get_session_user_id(request)

    memory_context = body.get("memory_context", "")
    if not memory_context:
        try:
            memory_context = summarize_user_profile(current_category=category, user_id=user_id)
        except Exception as exc:
            _logger.debug("[rubric] memory context unavailable: %s", exc)
            memory_context = ""

    if memory_context and isinstance(profile, dict):
        existing = profile.get("preferences_summary", "")
        already_injected = memory_context.strip() and memory_context.strip() in existing
        if not already_injected:
            if existing:
                profile = {**profile, "preferences_summary": (
                    f"{existing}\n\nAdditional context from past searches:\n{memory_context}"
                )}
            else:
                profile = {**profile, "preferences_summary": memory_context}

    if isinstance(profile, dict) and not profile.get("intent"):
        req_intent = body.get("intent")
        if req_intent and isinstance(req_intent, dict):
            profile = {**profile, "intent": req_intent}

    return generate_rubric(category, criteria, profile)


# ---------------------------------------------------------------------------
# Search lifecycle
# ---------------------------------------------------------------------------

@app.post("/api/search")
@limiter.limit("10/minute")
def start_search(request: Request, req: SearchRequest, _auth: None = Depends(_check_api_key)) -> dict:
    user_id = _get_session_user_id(request)
    # Dedup: if an identical query is already in-flight, return its search_id instead of
    # launching a second full pipeline run (prevents double-click / rapid-retry cost duplication).
    existing = find_inflight_session(req.query)
    if existing:
        _logger.info("[search] dedup hit — returning existing in-flight session %s for query %r",
                     existing.search_id, req.query)
        return {"search_id": existing.search_id, "deduplicated": True}
    search_id = str(uuid.uuid4())
    create_search(search_id, req.query, req.category, req.region)
    update_search(search_id, profile=req.profile, rubric=req.rubric, status="running")
    session = create_session(search_id, req.query)
    options_with_qa = {
        **req.options,
        "qa_history": req.qa_history,
        "primary_noun": req.primary_noun or req.category.split("/")[-1].replace("-", " "),
        "user_id": user_id,
    }
    start_pipeline(session, req.category, req.region, req.profile, req.rubric, options_with_qa)
    return {"search_id": search_id}


@app.get("/api/search/{search_id}/stream")
async def stream_search(search_id: str, reconnect: bool = Query(False)) -> StreamingResponse:
    session = get_session(search_id)
    if not session:
        row = get_search(search_id)
        if row and row.get("status") == "done":
            async def _already_done():
                yield f"data: {json.dumps({'type': 'done', 'data': {'search_id': search_id, 'from_cache': False}})}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(_already_done(), media_type="text/event-stream",
                                     headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
        raise HTTPException(404, "Search session not found. It may have expired.")

    async def event_generator() -> AsyncGenerator[str, None]:
        loop = asyncio.get_event_loop()

        if reconnect and session._event_log:
            # Cap replay to prevent unbounded memory on reconnect after a long session
            for item in list(session._event_log)[-500:]:
                yield f"data: {json.dumps(item)}\n\n"
            if session.status in ("done", "error", "cancelled"):
                yield "data: [DONE]\n\n"
                return

        while True:
            try:
                item = await loop.run_in_executor(None, _drain_with_timeout, session)
            except Exception as exc:
                yield f"data: {json.dumps({'type': 'error', 'data': {'message': str(exc)}})}\n\n"
                break

            if item is None:
                yield "data: [DONE]\n\n"
                break
            yield f"data: {json.dumps(item)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _drain_with_timeout(session, timeout: float = 30.0):
    import queue as _queue
    try:
        return session.events.get(timeout=timeout)
    except _queue.Empty:
        return {"type": "heartbeat", "data": {}}


@app.get("/api/search/{search_id}")
def get_search_result(search_id: str) -> dict:
    row = get_search(search_id)
    if not row:
        raise HTTPException(404, "Search not found")
    return row


@app.post("/api/search/{search_id}/cancel")
def cancel_search_endpoint(search_id: str) -> dict:
    """Stop a running pipeline. Idempotent — safe to call even if already done."""
    cancelled = cancel_session(search_id)
    try:
        update_search(search_id, status="cancelled")
    except Exception as exc:
        _logger.debug("[cancel] DB update failed for %s: %s", search_id, exc)
    return {"cancelled": cancelled, "search_id": search_id}


def _strip_profile_pii(search: dict) -> dict:
    """Remove interview Q&A from a search row before sending to the client.

    profile.interview contains verbatim user answers — PII that has no place
    in a list endpoint visible to any authenticated caller. The preferences_summary
    (a sanitised text blob) is kept for display purposes.
    """
    profile = search.get("profile")
    if isinstance(profile, dict) and "interview" in profile:
        search = {**search, "profile": {k: v for k, v in profile.items() if k != "interview"}}
    return search


@app.get("/api/searches")
def list_all_searches(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    items = [_strip_profile_pii(s) for s in list_searches(limit=limit, offset=offset)]
    return {"searches": items, "limit": limit, "offset": offset}


# ---------------------------------------------------------------------------
# Profile persistence (user-scoped)
# ---------------------------------------------------------------------------

@app.get("/api/profile/{category:path}")
def get_profile_endpoint(request: Request, category: str) -> dict:
    user_id = _get_user_id(request)
    data = get_profile(_profile_key(user_id, category))
    if not data and user_id != "default":
        # Fallback: legacy unscoped profile (backwards compatibility)
        data = get_profile(category)
    if not data:
        raise HTTPException(404, "Profile not found")
    return data


@app.post("/api/profile/{category:path}")
def save_profile_endpoint(request: Request, category: str, req: SaveProfileRequest) -> dict:
    user_id = _get_user_id(request)
    key = _profile_key(user_id, category)
    with _get_profile_write_lock(key):
        save_profile_db(key, req.profile)
    return {"saved": True}


# ---------------------------------------------------------------------------
# Price fetching
# ---------------------------------------------------------------------------

@app.post("/api/prices")
def fetch_prices_endpoint(req: PricesRequest) -> dict:
    if not _PRICE_FETCHER_AVAILABLE:
        raise HTTPException(503, "Price fetcher not available")
    try:
        results = _fetch_prices(req.products, region=req.region)
        return {"prices": results}
    except Exception as exc:
        raise HTTPException(500, f"Price fetch failed: {exc}")


# ---------------------------------------------------------------------------
# v7: Memory endpoints (all user-scoped via X-Session-ID header)
# ---------------------------------------------------------------------------

@app.get("/api/memory/context")
def get_memory_context(request: Request, q: str = Query(""), category: str = Query("")) -> dict:
    """Return relevant remembered signals for a query. Used to pre-fill interview context."""
    user_id = _get_user_id(request)
    try:
        signals = find_relevant_signals(
            q or category,
            k=5,
            min_similarity=0.65,
            current_category=category or None,
            user_id=user_id,
        )
        profile_summary = summarize_user_profile(current_category=category or None, user_id=user_id)
        return {
            "signals": signals,
            "profile_summary": profile_summary,
            "has_memory": len(signals) > 0,
        }
    except Exception as exc:
        _logger.warning("[api/memory] context fetch failed (non-fatal): %s", exc)
        return {"signals": [], "profile_summary": "", "has_memory": False}


@app.get("/api/memory/signals")
def list_memory_signals(request: Request, limit: int = Query(100, ge=1, le=500)) -> dict:
    user_id = _get_user_id(request)
    try:
        signals = list_user_signals(limit=limit, user_id=user_id)
        return {"signals": signals, "count": len(signals)}
    except Exception as exc:
        raise HTTPException(500, f"Memory unavailable: {exc}")


@app.delete("/api/memory/signals/{signal_id}")
@limiter.limit("30/minute")
def forget_signal(request: Request, signal_id: str) -> dict:
    user_id = _get_user_id(request)
    try:
        deleted = delete_signal(signal_id, user_id=user_id)
        return {"deleted": deleted}
    except Exception as exc:
        raise HTTPException(500, f"Delete failed: {exc}")


@app.get("/api/memory/products")
def list_memory_products(request: Request, limit: int = Query(100, ge=1, le=500)) -> dict:
    user_id = _get_user_id(request)
    try:
        products = list_product_memories(limit=limit, user_id=user_id)
        return {"products": products, "count": len(products)}
    except Exception as exc:
        raise HTTPException(500, f"Memory unavailable: {exc}")


@app.post("/api/memory/products/{product_name:path}/status")
@limiter.limit("30/minute")
def update_product_status(request: Request, product_name: str, req: ProductStatusRequest) -> dict:
    valid = {"considered", "rejected", "purchased", "returned"}
    if req.status not in valid:
        raise HTTPException(400, f"status must be one of: {valid}")
    user_id = _get_user_id(request)
    try:
        save_product_memory(
            product_name,
            category=req.category,
            status=req.status,
            our_score=req.our_score,
            user_feedback=req.feedback,
            user_id=user_id,
        )
        return {"saved": True, "product": product_name, "status": req.status}
    except Exception as exc:
        raise HTTPException(500, f"Save failed: {exc}")


@app.delete("/api/memory/products/{product_name:path}")
@limiter.limit("30/minute")
def forget_product_memory(request: Request, product_name: str) -> dict:
    user_id = _get_user_id(request)
    try:
        deleted = delete_product_memory(product_name, user_id=user_id)
        return {"deleted": deleted, "product": product_name}
    except Exception as exc:
        raise HTTPException(500, f"Delete failed: {exc}")


@app.post("/api/memory/bought")
@limiter.limit("20/minute")
def record_purchase(request: Request, req: BoughtRequest) -> dict:
    """Record that the user bought a product. Optionally extracts a preference signal from feedback."""
    user_id = _get_user_id(request)
    try:
        save_product_memory(
            req.product_name,
            category=req.category,
            status="purchased",
            our_score=req.our_score,
            user_feedback=req.feedback,
            user_id=user_id,
        )
        signals_saved = []
        if req.feedback:
            synthetic_qa = [
                {"question": f"How was the {req.product_name}?", "answer": req.feedback}
            ]
            signals_saved = extract_and_save_signals(req.category, synthetic_qa, user_id=user_id)
        return {
            "saved": True,
            "product": req.product_name,
            "signals_extracted": len(signals_saved),
        }
    except Exception as exc:
        raise HTTPException(500, f"Save failed: {exc}")


@app.delete("/api/memory/all")
def wipe_all_memory(request: Request, _auth: None = Depends(_check_api_key)) -> dict:
    user_id = _get_user_id(request)
    try:
        result = clear_all_memory(user_id=user_id)
        return {"cleared": True, **result}
    except Exception as exc:
        raise HTTPException(500, f"Wipe failed: {exc}")


# ---------------------------------------------------------------------------
# Auth: legacy-data adoption (guest → authenticated account merge)
# ---------------------------------------------------------------------------

@app.post("/api/auth/adopt-legacy")
@limiter.limit("10/hour")
def adopt_legacy_data(
    request: Request,
    legacy_session_id: str = Query(..., min_length=4, max_length=64),
    user_id: str = Depends(_require_auth),
) -> dict:
    """
    Merge data from a guest session into the authenticated user's account.
    Called once after first login so prior searches and signals carry over.
    Rate-limited to 10/hour to prevent abuse.
    """
    if not legacy_session_id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(400, "Invalid legacy session ID format")
    counts = reassign_user_data(from_user_id=legacy_session_id, to_user_id=user_id)
    return {"merged": True, "from": legacy_session_id, "to": user_id, "rows": counts}


# ---------------------------------------------------------------------------
# Health + diagnostics
# ---------------------------------------------------------------------------

@app.get("/api/providers/status")
def providers_status() -> dict:
    """Detailed per-provider status: configured, session alive, circuit breaker state."""
    return {"providers": get_provider_status()}


@app.get("/api/search/{search_id}/diagnostics")
def get_diagnostics(search_id: str) -> dict:
    """Return pipeline diagnostics for a search (partial while running, full when done)."""
    session = get_session(search_id)
    if session:
        return {
            "search_id": search_id,
            "status": session.status,
            "elapsed_s": round(time.time() - session._created_at, 1),
            "stats": session.stats,
        }
    row = get_search(search_id)
    if not row:
        raise HTTPException(404, "Search not found")
    return {
        "search_id": search_id,
        "status": row.get("status"),
        "stats": {},
    }


# ---------------------------------------------------------------------------
# Export endpoints — CSV, PDF, shareable links
# ---------------------------------------------------------------------------

@app.get("/api/search/{search_id}/csv")
def export_csv(search_id: str):
    """Download scored products as a CSV file."""
    from fastapi.responses import Response as _Response
    row = get_search(search_id)
    if not row:
        raise HTTPException(404, "Search not found")
    if row.get("status") != "done" or not row.get("scoredProducts"):
        raise HTTPException(422, "Results not ready — search must be complete before exporting")
    from export import generate_csv
    csv_bytes = generate_csv(row)
    safe_q = (row.get("query", "results") or "results")[:40].replace(" ", "_")
    safe_q = "".join(c for c in safe_q if c.isalnum() or c == "_")
    return _Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="shopsense_{safe_q}.csv"'},
    )


@app.get("/api/search/{search_id}/pdf")
def export_pdf(search_id: str):
    """Download search results as a formatted PDF report."""
    from fastapi.responses import Response as _Response
    row = get_search(search_id)
    if not row:
        raise HTTPException(404, "Search not found")
    if row.get("status") != "done" or not row.get("scoredProducts"):
        raise HTTPException(422, "Results not ready — search must be complete before exporting")
    from export import generate_pdf
    pdf_bytes = generate_pdf(row)
    safe_q = (row.get("query", "results") or "results")[:40].replace(" ", "_")
    safe_q = "".join(c for c in safe_q if c.isalnum() or c == "_")
    return _Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="shopsense_{safe_q}.pdf"'},
    )


@app.post("/api/search/{search_id}/share")
def create_share(search_id: str, request: Request):
    """Generate a shareable short link for this search result."""
    import secrets
    row = get_search(search_id)
    if not row:
        raise HTTPException(404, "Search not found")
    if row.get("status") != "done":
        raise HTTPException(422, "Search must be complete before sharing")

    token = secrets.token_urlsafe(16)
    create_share_token(token, search_id)

    # Build the share URL using the frontend origin
    origin = os.environ.get("FRONTEND_URL", "http://localhost:3000")
    share_url = f"{origin}/s/{token}"
    return {"token": token, "share_url": share_url}


@app.get("/api/share/{token}")
def resolve_share(token: str):
    """Resolve a share token to its search_id."""
    search_id = resolve_share_token(token)
    if not search_id:
        raise HTTPException(404, "Share link not found or expired")
    return {"search_id": search_id}


@app.get("/api/health")
def health() -> dict:
    db_ok = True
    memory_ok = True
    try:
        init_db()
    except Exception as exc:
        _logger.warning("[health] DB check failed: %s", exc)
        db_ok = False

    try:
        list_user_signals(limit=1)
    except Exception as exc:
        _logger.debug("[health] memory check failed: %s", exc)
        memory_ok = False

    return {
        "status": "ok",
        "db": "ok" if db_ok else "error",
        "memory": "ok" if memory_ok else "unavailable",
        "providers": get_provider_status(),
    }
