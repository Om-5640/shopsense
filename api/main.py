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
import json
import asyncio
import uuid
from pathlib import Path
from typing import AsyncGenerator, Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# Ensure both api/ dir and project root are importable.
_API_DIR = Path(__file__).parent
_ROOT = _API_DIR.parent
for _p in [str(_API_DIR), str(_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from db import init_db, create_search, update_search, get_search, list_searches
from db import get_profile, save_profile_db
from pipeline_runner import create_session, start_pipeline, get_session

app = FastAPI(title="Shopping Research Agent v7", version="7.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


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
def detect(req: DetectRequest) -> dict:
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
    from interview import generate_next_question, _identify_uncovered_criteria, MAX_QUESTIONS, MIN_QUESTIONS, COVERAGE_TARGET

    qa = req.qa_history
    force_continue = (len(qa) + 1) <= MIN_QUESTIONS

    if not force_continue:
        uncovered = _identify_uncovered_criteria(req.criteria, qa)
        coverage = (len(req.criteria) - len(uncovered)) / max(len(req.criteria), 1)
        if coverage >= COVERAGE_TARGET or len(qa) >= MAX_QUESTIONS:
            return {"question": "", "why_asking": "", "targets_criterion": "", "is_done": True}

    result = generate_next_question(req.category, req.criteria, qa, initial_query=req.initial_query)
    if force_continue:
        result["is_done"] = False
    return result


@app.post("/api/interview/summarize")
def interview_summarize(req: InterviewSummarizeRequest) -> dict:
    from interview import _summarize_preferences
    summary = _summarize_preferences(req.category, req.qa_history)
    return {"preferences_summary": summary}


# ---------------------------------------------------------------------------
# Rubric generation
# ---------------------------------------------------------------------------

@app.post("/api/rubric")
def generate_rubric_endpoint(body: dict) -> dict:
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
        if existing:
            profile = {**profile, "preferences_summary": memory_context + "\n\n" + existing}
        else:
            profile = {**profile, "preferences_summary": memory_context}

    rubric = generate_rubric(category, criteria, profile)
    return rubric


# ---------------------------------------------------------------------------
# Search lifecycle
# ---------------------------------------------------------------------------

@app.post("/api/search")
def start_search(req: SearchRequest) -> dict:
    search_id = str(uuid.uuid4())
    create_search(search_id, req.query, req.category, req.region)
    update_search(search_id, profile=req.profile, rubric=req.rubric, status="running")
    session = create_session(search_id, req.query)
    # Merge qa_history and primary_noun into options
    options_with_qa = {
        **req.options,
        "qa_history": req.qa_history,
        "primary_noun": req.primary_noun or req.category.split("/")[-1].replace("-", " "),
    }
    start_pipeline(session, req.category, req.region, req.profile, req.rubric, options_with_qa)
    return {"search_id": search_id}


@app.get("/api/search/{search_id}/stream")
async def stream_search(search_id: str) -> StreamingResponse:
    session = get_session(search_id)
    if not session:
        raise HTTPException(404, "Search session not found. It may have expired.")

    async def event_generator() -> AsyncGenerator[str, None]:
        loop = asyncio.get_event_loop()
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
def get_memory_context(q: str = Query(""), category: str = Query("")) -> dict:
    """
    Given a query (or category), return relevant remembered signals.
    Used by the research page to pre-fill interview context.
    """
    try:
        from memory import find_relevant_signals, summarize_user_profile
        signals = find_relevant_signals(
            q or category,
            k=5,
            min_similarity=0.65,
            current_category=category or None,
        )
        profile_summary = summarize_user_profile(current_category=category or None)
        return {
            "signals": signals,
            "profile_summary": profile_summary,
            "has_memory": len(signals) > 0,
        }
    except Exception as exc:
        # Memory unavailable — not fatal
        print(f"[api/memory] context failed (non-fatal): {exc}")
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
def wipe_all_memory() -> dict:
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
