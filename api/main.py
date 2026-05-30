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
import uuid
from pathlib import Path
from typing import AsyncGenerator, Any, Optional

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Ensure both api/ dir and project root are importable.
_API_DIR = Path(__file__).parent
_ROOT = _API_DIR.parent
for _p in [str(_API_DIR), str(_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from db import init_db, create_search, update_search, get_search, list_searches
from db import get_profile, save_profile_db
import logging as _logging
from pipeline_runner import create_session, start_pipeline, get_session, cancel_session, cleanup_old_sessions

_logger = _logging.getLogger(__name__)


async def _session_cleanup_loop() -> None:
    while True:
        await asyncio.sleep(3600)  # every hour
        try:
            removed = cleanup_old_sessions()
            if removed:
                _logger.info("[session_cleanup] removed %d stale sessions", removed)
        except Exception:
            pass

@asynccontextmanager
async def lifespan(app: FastAPI):
    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    init_db()
    # Purge cache files older than 24h at startup to prevent unbounded disk growth (MEMORY-04)
    try:
        import cache as _cache_mod
        _cache_mod.purge_expired(max_age_seconds=86400)
    except Exception:
        pass
    cleanup_task = asyncio.create_task(_session_cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# Rate limiting (slowapi) — protects against quota-drain attacks
# ---------------------------------------------------------------------------

limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])

app = FastAPI(title="Shopping Research Agent v7", version="7.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ---------------------------------------------------------------------------
# Optional API-key authentication
# Set API_SECRET_KEY env var to enable. Unset = auth disabled (dev mode).
# Clients send: Authorization: Bearer <key>   OR   X-API-Key: <key>
# ---------------------------------------------------------------------------

_API_SECRET_KEY = os.environ.get("API_SECRET_KEY", "")


def _check_api_key(request: Request) -> None:
    if not _API_SECRET_KEY:
        return  # auth disabled — development mode
    # Accept key via Authorization: Bearer <key> or X-API-Key: <key> header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer "):]
        if token == _API_SECRET_KEY:
            return
    api_key_header = request.headers.get("X-API-Key", "")
    if api_key_header == _API_SECRET_KEY:
        return
    raise HTTPException(status_code=401, detail="Invalid or missing API key")


_CORS_ENV = os.environ.get("CORS_ORIGINS", "")
if not _CORS_ENV:
    import logging as _cors_log
    _cors_log.getLogger(__name__).warning(
        "[SEC-08] CORS_ORIGINS env var not set — defaulting to localhost:3000. "
        "Set CORS_ORIGINS to your production frontend URL(s) to prevent localhost CORS abuse."
    )
_CORS_ORIGINS = [
    o.strip()
    for o in (_CORS_ENV or "http://localhost:3000,http://127.0.0.1:3000").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response


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
    initial_query: str = ""  # original search query — used to skip already-answered template questions


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
    primary_noun: str = ""  # v8: product type constraint for the analyzer


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
    from category import detect_category, _sanitize_slug
    from reddit_fetch import detect_region, has_ambiguous_price

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
    from criteria import generate_criteria
    items = generate_criteria(req.category)
    return {"category": req.category, "criteria": items}


# ---------------------------------------------------------------------------
# Interview (stateless — client holds Q&A history)
# ---------------------------------------------------------------------------

@app.post("/api/interview/next")
def interview_next(req: InterviewNextRequest) -> dict:
    from interview import (generate_next_question, _identify_uncovered_criteria,
                           MAX_QUESTIONS, MIN_QUESTIONS, _dynamic_coverage_target)

    qa = req.qa_history
    force_continue = (len(qa) + 1) <= MIN_QUESTIONS

    if not force_continue:
        uncovered = _identify_uncovered_criteria(req.criteria, qa, req.initial_query)
        coverage = (len(req.criteria) - len(uncovered)) / max(len(req.criteria), 1)
        dyn_target = _dynamic_coverage_target(len(req.criteria))
        if coverage >= dyn_target or len(qa) >= MAX_QUESTIONS:
            return {"question": "", "why_asking": "", "targets_criterion": "", "is_done": True}

    # Pass memory_context to the question generator so it avoids asking about
    # criteria already answered by signals from the user's past searches.
    result = generate_next_question(
        req.category,
        req.criteria,
        qa,
        initial_query=req.initial_query,
        memory_context=req.memory_context or [],
    )
    if force_continue:
        result["is_done"] = False
    return result


@app.post("/api/interview/process_message")
@limiter.limit("60/minute")
def process_message_endpoint(request: Request, req: ProcessMessageRequest) -> dict:
    from interview import process_message
    return process_message(req.category, req.criteria, req.current_question, req.message, req.qa_history)


@app.post("/api/interview/summarize")
def interview_summarize(req: InterviewSummarizeRequest) -> dict:
    from interview import _summarize_and_extract_intent
    summary, intent = _summarize_and_extract_intent(req.category, req.qa_history)
    return {"preferences_summary": summary, "intent": intent}


# ---------------------------------------------------------------------------
# Rubric generation
# ---------------------------------------------------------------------------

@app.post("/api/rubric")
@limiter.limit("30/minute")
def generate_rubric_endpoint(request: Request, body: dict) -> dict:
    from rubric import generate_rubric

    category = body.get("category", "")
    criteria = body.get("criteria", [])
    profile = body.get("profile", {})

    # v7: inject memory profile summary into rubric generation
    memory_context = body.get("memory_context", "")
    if not memory_context:
        try:
            from memory import summarize_user_profile
            memory_context = summarize_user_profile(current_category=category)
        except Exception:
            memory_context = ""

    if memory_context and isinstance(profile, dict):
        existing = profile.get("preferences_summary", "")
        # ENTROPY-01: only inject memory context if it's not already present in the summary,
        # preventing double-injection when the frontend passes memory_context AND the profile
        # was already enriched by a prior call.
        already_injected = memory_context.strip() and memory_context.strip() in existing
        if not already_injected:
            if existing:
                # Current-session interview ALWAYS takes precedence; memory is supplemental
                profile = {**profile, "preferences_summary": (
                    f"{existing}\n\nAdditional context from past searches:\n{memory_context}"
                )}
            else:
                profile = {**profile, "preferences_summary": memory_context}

    # Carry intent from request body into profile if frontend sent it but profile didn't
    if isinstance(profile, dict) and not profile.get("intent"):
        req_intent = body.get("intent")
        if req_intent and isinstance(req_intent, dict):
            profile = {**profile, "intent": req_intent}

    rubric = generate_rubric(category, criteria, profile)
    return rubric


# ---------------------------------------------------------------------------
# Search lifecycle
# ---------------------------------------------------------------------------

@app.post("/api/search")
@limiter.limit("10/minute")
def start_search(request: Request, req: SearchRequest, _auth: None = Depends(_check_api_key)) -> dict:
    user_id = _get_session_user_id(request)
    search_id = str(uuid.uuid4())
    create_search(search_id, req.query, req.category, req.region)
    update_search(search_id, profile=req.profile, rubric=req.rubric, status="running")
    session = create_session(search_id, req.query)
    # Merge qa_history, primary_noun, and user_id into options
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
        # Session may have finished and been evicted — tell the client to fetch results
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

        # Reconnect: replay the event log so the client catches up on missed events
        if reconnect and session._event_log:
            for item in list(session._event_log):
                yield f"data: {json.dumps(item)}\n\n"
            # If session already finished, close immediately
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
    except Exception:
        pass
    return {"cancelled": cancelled, "search_id": search_id}


@app.get("/api/searches")
def list_all_searches(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    items = list_searches(limit=limit, offset=offset)
    return {"searches": items, "limit": limit, "offset": offset}


# ---------------------------------------------------------------------------
# Profile persistence
# ---------------------------------------------------------------------------

@app.get("/api/profile/{category:path}")
def get_profile_endpoint(category: str) -> dict:
    data = get_profile(category)
    if not data:
        raise HTTPException(404, "Profile not found")
    return data


@app.post("/api/profile/{category:path}")
def save_profile_endpoint(category: str, req: SaveProfileRequest) -> dict:
    save_profile_db(category, req.profile)
    return {"saved": True}


# ---------------------------------------------------------------------------
# Price fetching
# ---------------------------------------------------------------------------

@app.post("/api/prices")
def fetch_prices_endpoint(req: PricesRequest) -> dict:
    try:
        from price_fetcher import fetch_prices
        results = fetch_prices(req.products, region=req.region)
        return {"prices": results}
    except Exception as exc:
        raise HTTPException(500, f"Price fetch failed: {exc}")


# ---------------------------------------------------------------------------
# v7: Memory endpoints
# ---------------------------------------------------------------------------

@app.get("/api/memory/context")
def get_memory_context(request: Request, q: str = Query(""), category: str = Query("")) -> dict:
    """
    Given a query (or category), return relevant remembered signals.
    Used by the research page to pre-fill interview context.
    """
    user_id = _get_session_user_id(request)
    try:
        from memory import find_relevant_signals, summarize_user_profile
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
        # Memory unavailable — not fatal
        _logger.warning("[api/memory] context fetch failed (non-fatal): %s", exc)
        return {"signals": [], "profile_summary": "", "has_memory": False}


@app.get("/api/memory/signals")
def list_memory_signals(limit: int = Query(100, ge=1, le=500)) -> dict:
    try:
        from memory import list_user_signals
        signals = list_user_signals(limit=limit)
        return {"signals": signals, "count": len(signals)}
    except Exception as exc:
        raise HTTPException(500, f"Memory unavailable: {exc}")


@app.delete("/api/memory/signals/{signal_id}")
def forget_signal(signal_id: str) -> dict:
    try:
        from memory import delete_signal
        deleted = delete_signal(signal_id)
        return {"deleted": deleted}
    except Exception as exc:
        raise HTTPException(500, f"Delete failed: {exc}")


@app.get("/api/memory/products")
def list_memory_products(limit: int = Query(100, ge=1, le=500)) -> dict:
    try:
        from memory import list_product_memories
        products = list_product_memories(limit=limit)
        return {"products": products, "count": len(products)}
    except Exception as exc:
        raise HTTPException(500, f"Memory unavailable: {exc}")


@app.post("/api/memory/products/{product_name:path}/status")
def update_product_status(product_name: str, req: ProductStatusRequest) -> dict:
    valid = {"considered", "rejected", "purchased", "returned"}
    if req.status not in valid:
        raise HTTPException(400, f"status must be one of: {valid}")
    try:
        from memory import save_product_memory
        save_product_memory(
            product_name,
            category=req.category,
            status=req.status,
            our_score=req.our_score,
            user_feedback=req.feedback,
        )
        return {"saved": True, "product": product_name, "status": req.status}
    except Exception as exc:
        raise HTTPException(500, f"Save failed: {exc}")


@app.delete("/api/memory/products/{product_name:path}")
def forget_product_memory(product_name: str) -> dict:
    try:
        from memory import delete_product_memory
        deleted = delete_product_memory(product_name)
        return {"deleted": deleted, "product": product_name}
    except Exception as exc:
        raise HTTPException(500, f"Delete failed: {exc}")


@app.post("/api/memory/bought")
def record_purchase(req: BoughtRequest) -> dict:
    """Record that the user bought a product. Also creates a UserSignal from their feedback."""
    try:
        from memory import save_product_memory, extract_and_save_signals
        save_product_memory(
            req.product_name,
            category=req.category,
            status="purchased",
            our_score=req.our_score,
            user_feedback=req.feedback,
        )
        # If user left feedback, extract it as a signal for future searches
        signals_saved = []
        if req.feedback:
            synthetic_qa = [
                {"question": f"How was the {req.product_name}?", "answer": req.feedback}
            ]
            signals_saved = extract_and_save_signals(req.category, synthetic_qa)

        return {
            "saved": True,
            "product": req.product_name,
            "signals_extracted": len(signals_saved),
        }
    except Exception as exc:
        raise HTTPException(500, f"Save failed: {exc}")


@app.delete("/api/memory/all")
def wipe_all_memory(_auth: None = Depends(_check_api_key)) -> dict:
    try:
        from memory import clear_all_memory
        result = clear_all_memory()
        return {"cleared": True, **result}
    except Exception as exc:
        raise HTTPException(500, f"Wipe failed: {exc}")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/api/providers/status")
def providers_status() -> dict:
    """Detailed per-provider status: configured, session alive, circuit breaker state."""
    from agents import get_provider_status
    return {"providers": get_provider_status()}


@app.get("/api/search/{search_id}/diagnostics")
def get_diagnostics(search_id: str) -> dict:
    """
    Phase 11: Return pipeline diagnostics for a search.
    Available while running (partial) and after completion (full).
    """
    from pipeline_runner import get_session as _get_session
    import time as _time

    session = _get_session(search_id)
    if session:
        return {
            "search_id": search_id,
            "status": session.status,
            "elapsed_s": round(_time.time() - session._created_at, 1),
            "stats": session.stats,
        }
    # Session evicted — return what we have from DB
    row = get_search(search_id)
    if not row:
        raise HTTPException(404, "Search not found")
    return {
        "search_id": search_id,
        "status": row.get("status"),
        "stats": {},
    }


@app.get("/api/health")
def health() -> dict:
    from agents import get_provider_status

    db_ok = True
    memory_ok = True
    try:
        init_db()
    except Exception:
        db_ok = False

    try:
        from memory import list_user_signals
        list_user_signals(limit=1)
    except Exception:
        memory_ok = False

    return {
        "status": "ok",
        "db": "ok" if db_ok else "error",
        "memory": "ok" if memory_ok else "unavailable",
        "providers": get_provider_status(),
    }
