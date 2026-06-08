"""
User memory module — cross-search personalization layer.

Stores and retrieves:
  UserSignal      — durable preference/rejection signals extracted from interviews
  ProductMemory   — products the user has considered, bought, or returned

Memory is embedded (Gemini text-embedding-004) and retrieved by semantic similarity.
Works with both Postgres+pgvector (when POSTGRES_URL is set) and SQLite fallback.

Public API:
  extract_and_save_signals(category, qa_history, source_search_id)
  find_relevant_signals(query, k, min_similarity) → list of signal dicts
  save_product_memory(product_name, category, status, our_score, feedback)
  get_product_memory(product_name) → dict | None
  list_user_signals() → list
  list_product_memories() → list
  delete_signal(signal_id)
  clear_all_memory()
  summarize_user_profile() → str   (for injecting into LLM prompts)
"""

import datetime
import re
import sys
import time
import uuid
import logging
from pathlib import Path
from typing import Any, Optional

_logger = logging.getLogger(__name__)

# sys.path patch — needed because memory.py lives at project root but imports
# from api/. Remove once the package layout is consolidated.
_API_DIR = Path(__file__).parent / "api"
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from agents import run_agent
from embeddings import embed, embed_batch

try:
    from llm_client import _try_repair_json as _repair_json
except ImportError:
    import json as _json
    def _repair_json(raw: str) -> Any:  # type: ignore[misc]
        try:
            return _json.loads(raw)
        except Exception:
            return {}

# Module-level db imports — all-or-nothing; avoids repeated import overhead and
# surfaces missing-module errors at startup rather than inside request handlers.
try:
    from db import (
        save_signal as _db_save_signal,
        find_similar_signals as _db_find_similar,
        list_signals as _db_list_signals,
        save_product_memory as _db_save_product_memory,
        get_product_memory as _db_get_product_memory,
        list_product_memories as _db_list_product_memories,
        delete_product_memory as _db_delete_product_memory,
        delete_signal as _db_delete_signal,
        clear_signals as _db_clear_signals,
        clear_product_memories as _db_clear_product_memories,
    )
    _DB_AVAILABLE = True
except ImportError:
    _DB_AVAILABLE = False
    _logger.warning("[memory] db module not importable — persistence disabled")


# ── Constants ──────────────────────────────────────────────────────────────────

_VALID_TYPES     = frozenset({"preference", "rejection", "complaint"})
_VALID_STRENGTHS = frozenset({"strong", "moderate", "weak"})

# Rough token budget for summarize_user_profile prompt injection.
# Each signal ≈ 150 chars / ~40 tokens; cap keeps memory context < ~600 tokens.
_MAX_PROFILE_CHARS = 3_000


# ── Helpers ────────────────────────────────────────────────────────────────────

def _canonical_key(name: str) -> str:
    """Strip punctuation/spaces/case — mirrors cross_validate._canonical_key."""
    return re.sub(r"[\W_]", "", name.lower())


def _category_applies(hint: str, current_category: str) -> bool:
    """
    True when a signal stored under `hint` is relevant to `current_category`.
    Shared by find_relevant_signals (hard filter) and summarize_user_profile.
    """
    if hint == "any" or not current_category:
        return True
    cat = current_category.lower()
    return hint == cat or cat.startswith(f"{hint}/") or cat.startswith(f"{hint}-")


def _warn_default_user(fn_name: str, user_id: str) -> None:
    if user_id == "default":
        _logger.warning(
            "[memory] %s called with user_id='default' — all users share this memory bucket",
            fn_name,
        )


def _validate_signal(raw: Any) -> dict | None:
    """
    Validate and normalise a single signal dict from the LLM.
    Returns None for malformed entries so they are silently dropped.
    """
    if not isinstance(raw, dict):
        return None
    text = (raw.get("text") or "").strip()
    if not text:
        return None
    sig_type = raw.get("type", "preference")
    if sig_type not in _VALID_TYPES:
        _logger.debug("[memory] unknown signal type %r — defaulting to 'preference'", sig_type)
        sig_type = "preference"
    strength = raw.get("strength", "moderate")
    if strength not in _VALID_STRENGTHS:
        _logger.debug("[memory] unknown strength %r — defaulting to 'moderate'", strength)
        strength = "moderate"
    category_hint = (raw.get("category_hint") or "any").strip().lower()
    return {
        "type": sig_type,
        "text": text,
        "strength": strength,
        "category_hint": category_hint,
    }


# ── Signal extraction prompt ───────────────────────────────────────────────────

_EXTRACT_SYSTEM = """Extract DURABLE user preference signals from a product-research interview.

Keep only facts likely to remain relevant months later.

INCLUDE
- Physical traits: sensitive skin, wears glasses, flat feet, runs hot, fragrance-sensitive
- Long-term preferences: balanced audio, minimal design, dislikes bass-heavy sound
- Permanent aversions: allergies, fit issues, ingredient restrictions
- Lifestyle constraints: exercises daily, works from home, long commute
- Body-fit constraints: narrow feet, small wrists, large head circumference

EXCLUDE
- Budget or price constraints
- Current shopping intent
- Location/region
- Generic preferences ("good quality", "value for money")
- Temporary or one-time needs

Rules:
- strength: strong = physical constraint/allergy; moderate = explicit preference; weak = soft preference
- category_hint: "any" for cross-category facts; otherwise the most relevant category
- text: concise third-person fact — "Has sensitive dry skin", not "User said skin is dry"
- If no durable signals exist, return {"signals":[]}

Return ONLY valid JSON:
{"signals":[{"type":"preference"|"rejection"|"complaint","category_hint":"<category|any>","text":"<fact>","strength":"strong"|"moderate"|"weak"}]}"""


# ---------------------------------------------------------------------------
# Signal extraction (runs after interview completes)
# ---------------------------------------------------------------------------

def extract_and_save_signals(
    category: str,
    qa_history: list[dict],
    source_search_id: Optional[str] = None,
    user_id: str = "default",
) -> list[dict]:
    """
    Run signal_extractor agent on Q&A history, embed each signal, and persist.
    Returns list of extracted signal dicts (without embeddings).
    """
    _warn_default_user("extract_and_save_signals", user_id)

    if not qa_history:
        return []

    _SKIP_TOKENS = {"[Skipped]", "(skipped)"}
    answered = [
        e for e in qa_history
        if e.get("answer")
        and e["answer"] not in _SKIP_TOKENS
        and len(e["answer"].strip()) > 2
    ]
    if not answered:
        return []

    # Truncate runaway answers — keeps prompt size predictable
    _MAX_ANSWER_CHARS = 400
    qa_text = "\n".join(
        f"Q: {entry.get('question', '')}\nA: {entry['answer'][:_MAX_ANSWER_CHARS]}"
        for entry in answered
    )
    prompt = f"Category being researched: {category}\n\nInterview transcript:\n{qa_text}"

    # Retry up to 3 attempts with back-off — LLM calls can transiently fail
    last_exc: Exception | None = None
    raw: str = ""
    for attempt in range(3):
        try:
            raw = run_agent("signal_extractor", user_prompt=prompt, system=_EXTRACT_SYSTEM)
            break
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    else:
        _logger.warning("[memory] signal extraction LLM failed after 3 attempts: %s", last_exc)
        return []

    try:
        data = _repair_json(raw)
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict, got {type(data).__name__}")
        signals_unvalidated = data.get("signals", [])
    except Exception as exc:
        _logger.warning("[memory] signal extraction parse failed (non-fatal): %s", exc)
        return []

    # Strict schema validation — drop malformed entries
    signals_raw: list[dict] = []
    for raw_sig in signals_unvalidated:
        validated = _validate_signal(raw_sig)
        if validated is None:
            _logger.debug("[memory] dropped malformed signal: %r", raw_sig)
        else:
            signals_raw.append(validated)

    if not signals_raw:
        return []

    # Fix 3: Narrow over-broad category hints to prevent cross-product-type bleed.
    # When the LLM stores a signal under the top-level category (e.g. "electronics")
    # but the current research is product-specific (e.g. "electronics/earbuds"),
    # signals describing product-specific attributes (sound signature, fit, ANC quality)
    # must not bleed into unrelated subcategory searches (headphones, keyboards, etc.).
    # We only preserve the broad hint for cross-category-safe attributes (brand loyalty,
    # price sensitivity, build quality preference) which are genuinely universal.
    _CROSS_CATEGORY_SAFE_TERMS = frozenset({
        "brand", "budget", "price", "warranty", "durability", "build quality",
        "material", "design", "reliability", "longevity", "value", "aesthetic",
        "weight", "portability", "colour", "color",
    })
    if "/" in category:
        _top_level = category.split("/")[0].lower()
        for _sig in signals_raw:
            _hint = _sig.get("category_hint", "any")
            if _hint in ("any", category):
                continue
            # Broad parent hint (e.g. "electronics") for a specific category (e.g. "electronics/earbuds")
            if _hint == _top_level:
                _sig_lower = _sig.get("text", "").lower()
                _is_safe = any(term in _sig_lower for term in _CROSS_CATEGORY_SAFE_TERMS)
                if not _is_safe:
                    _logger.debug(
                        "[memory] narrowed hint %r → %r for signal: %s",
                        _hint, category, _sig.get("text"),
                    )
                    _sig["category_hint"] = category

    if not _DB_AVAILABLE:
        _logger.warning("[memory] db not available — signals will not be persisted")
        return signals_raw

    # Embed all signal texts in one batch call
    texts = [s["text"] for s in signals_raw]
    embeddings = embed_batch(texts)

    # Guard against partial embed_batch failure (len mismatch = silent crash)
    if len(embeddings) != len(signals_raw):
        _logger.warning(
            "[memory] embed_batch returned %d embeddings for %d signals — truncating to min",
            len(embeddings), len(signals_raw),
        )

    saved = []
    for sig, emb in zip(signals_raw, embeddings):
        sig_id = "sig_" + uuid.uuid4().hex[:16]
        try:
            _db_save_signal(
                signal_id=sig_id,
                signal_type=sig["type"],
                text=sig["text"],
                embedding=emb,
                category=sig["category_hint"] or category,
                strength=sig["strength"],
                source_search_id=source_search_id,
                user_id=user_id,
            )
            saved.append({"id": sig_id, **sig})
        except Exception as exc:
            _logger.warning("[memory] save_signal failed (non-fatal): %s", exc)

    _logger.info("[memory] extracted and saved %d signals from interview", len(saved))
    return saved


# ---------------------------------------------------------------------------
# Fix 15: Signal time-decay
# ---------------------------------------------------------------------------
# Half-life of 90 days: a preference stored 3 months ago counts as ~50% weight;
# at 6 months it's ~25%; at 1 year it's ~6%.  Minimum floor of 0.05 ensures old
# signals are never completely invisible — they still influence, just weakly.

_DECAY_HALFLIFE_DAYS: float = 90.0
_DECAY_FLOOR: float = 0.05
_STALE_THRESHOLD_DAYS: int = 90    # signals older than this are flagged as stale


def _signal_decay_weight(created_at_iso: str | None) -> float:
    """Return a [DECAY_FLOOR, 1.0] multiplier based on signal age.

    Newer signals count more; half-life is 90 days.
    Returns 1.0 when timestamp is missing (benefit of the doubt).
    """
    if not created_at_iso:
        return 1.0
    try:
        # Handle both "2024-03-15T12:00:00Z" and "2024-03-15T12:00:00.000000"
        ts = created_at_iso.replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        age_days = (datetime.datetime.now(datetime.timezone.utc) - dt).total_seconds() / 86400
        weight = 0.5 ** (age_days / _DECAY_HALFLIFE_DAYS)
        return max(_DECAY_FLOOR, round(weight, 4))
    except Exception:
        return 1.0


def _is_stale_signal(created_at_iso: str | None) -> bool:
    """Return True when a signal is older than _STALE_THRESHOLD_DAYS."""
    if not created_at_iso:
        return False
    try:
        ts = created_at_iso.replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        age_days = (datetime.datetime.now(datetime.timezone.utc) - dt).total_seconds() / 86400
        return age_days > _STALE_THRESHOLD_DAYS
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Signal retrieval
# ---------------------------------------------------------------------------

def find_relevant_signals(
    query: str,
    k: int = 5,
    min_similarity: float = 0.7,
    current_category: Optional[str] = None,
    user_id: str = "default",
) -> list[dict]:
    """
    Retrieve top-k signals most relevant to `query` via embedding similarity.

    Category filtering on top of similarity:
      - category_hint == "any"              → include if similarity ≥ min_similarity
      - category_hint == current_category   → include if similarity ≥ min_similarity - 0.1 (looser)
      - category_hint != current_category   → include only if similarity ≥ min_similarity + 0.15 (tighter)
    """
    _warn_default_user("find_relevant_signals", user_id)

    if not _DB_AVAILABLE:
        return []

    # Skip the embedding API call entirely when the user has no stored signals.
    # On a fresh install (or new user) every search would otherwise waste one embed call.
    try:
        if not _db_list_signals(user_id=user_id, limit=1):
            return []
    except Exception:
        pass

    query_vec = embed(query)
    if query_vec is None:
        return []

    try:
        raw_results = _db_find_similar(query_vec, k=k * 3, min_similarity=0.0, user_id=user_id)
    except Exception as exc:
        _logger.warning("[memory] find_similar_signals failed (non-fatal): %s", exc)
        return []

    filtered = []
    for r in raw_results:
        sim = float(r.get("similarity") or 0.0)
        hint = (r.get("category") or r.get("categoryHint") or "any").lower()
        cat_lc = (current_category or "").lower()

        # Hard-block signals from incompatible categories (mirrors summarize_user_profile)
        if not _category_applies(hint, cat_lc):
            continue

        if hint == "any":
            threshold = min_similarity if not cat_lc else min_similarity + 0.05
        elif hint == cat_lc:
            threshold = max(0.5, min_similarity - 0.1)
        else:
            # Parent category (e.g. "electronics") matching a sub-category search
            threshold = min_similarity + 0.10

        # Fix 15: apply time-decay — older signals need higher raw similarity to pass
        decay = _signal_decay_weight(r.get("createdAt"))
        effective_sim = sim * decay
        r["decay_weight"] = decay  # expose to callers (UI can show staleness)

        if effective_sim >= threshold:
            filtered.append(r)

    filtered.sort(key=lambda x: -(float(x.get("similarity") or 0.0) * float(x.get("decay_weight") or 1.0)))
    return filtered[:k]


def summarize_user_profile(current_category: Optional[str] = None, user_id: str = "default") -> str:
    """
    Generate a compact text summary of known user preferences for prompt injection.
    Capped at _MAX_PROFILE_CHARS to prevent prompt bloat for heavy users.
    Returns "" if no signals exist.
    """
    _warn_default_user("summarize_user_profile", user_id)

    if not _DB_AVAILABLE:
        return ""

    try:
        # Fetch a reasonable window; token budget below provides the real cap
        signals = _db_list_signals(user_id=user_id, limit=100)
    except Exception:
        return ""

    if not signals:
        return ""

    cat_lc = (current_category or "").lower()
    relevant = [
        s for s in signals
        if _category_applies((s.get("category") or "any").lower(), cat_lc)
    ]
    if not relevant:
        return ""

    # Fix 15: sort by decay-adjusted strength — fresh strong > stale strong > fresh moderate
    def _sort_key(s: dict) -> float:
        base = 1.0 if s.get("strength") == "strong" else 0.6
        return base * _signal_decay_weight(s.get("createdAt"))

    relevant.sort(key=_sort_key, reverse=True)
    strong   = [s for s in relevant if s.get("strength") == "strong"]
    moderate = [s for s in relevant if s.get("strength") == "moderate"]

    lines = ["Remembered user preferences (from past searches):"]
    chars = len(lines[0])

    for s in strong[:10]:
        tag  = f"[{s.get('signalType', 'preference')}]"
        stale_note = " (older preference — may no longer apply)" if _is_stale_signal(s.get("createdAt")) else ""
        line = f"  • {tag} {s['text']}{stale_note}"
        if chars + len(line) > _MAX_PROFILE_CHARS:
            break
        lines.append(line)
        chars += len(line)

    for s in moderate[:8]:
        tag  = f"[{s.get('signalType', 'preference')}]"
        stale_note = " (older preference — may no longer apply)" if _is_stale_signal(s.get("createdAt")) else ""
        line = f"  • {tag} {s['text']}{stale_note}"
        if chars + len(line) > _MAX_PROFILE_CHARS:
            break
        lines.append(line)
        chars += len(line)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Product memory
# ---------------------------------------------------------------------------

def save_product_memory(
    product_name: str,
    category: str,
    status: str = "considered",
    our_score: Optional[float] = None,
    user_feedback: Optional[str] = None,
    user_id: str = "default",
) -> bool:
    """Upsert a product memory record. Returns True on success."""
    if not _DB_AVAILABLE:
        return False
    canonical = _canonical_key(product_name)
    try:
        _db_save_product_memory(canonical, category, status, our_score, user_feedback, user_id)
        return True
    except Exception as exc:
        _logger.warning("[memory] save_product_memory failed (non-fatal): %s", exc)
        return False


def get_product_memory(product_name: str, user_id: str = "default") -> Optional[dict]:
    if not _DB_AVAILABLE:
        return None
    canonical = _canonical_key(product_name)
    try:
        return _db_get_product_memory(canonical, user_id=user_id)
    except Exception:
        return None


def list_user_signals(limit: int = 200, user_id: str = "default") -> list[dict]:
    if not _DB_AVAILABLE:
        return []
    try:
        signals = _db_list_signals(user_id=user_id, limit=limit)
        # Fix 15: attach decay_weight and is_stale so UI and cache-key logic can use them
        for s in signals:
            s["decay_weight"] = _signal_decay_weight(s.get("createdAt"))
            s["is_stale"] = _is_stale_signal(s.get("createdAt"))
        return signals
    except Exception:
        return []


def list_product_memories(limit: int = 100, user_id: str = "default") -> list[dict]:
    if not _DB_AVAILABLE:
        return []
    try:
        return _db_list_product_memories(user_id=user_id, limit=limit)
    except Exception:
        return []


def delete_product_memory(product_name: str, user_id: str = "default") -> bool:
    if not _DB_AVAILABLE:
        return False
    canonical = _canonical_key(product_name)
    try:
        return _db_delete_product_memory(canonical, user_id=user_id)
    except Exception:
        return False


def delete_signal(signal_id: str, user_id: str = "default") -> bool:
    if not _DB_AVAILABLE:
        return False
    try:
        return _db_delete_signal(signal_id, user_id=user_id)
    except Exception:
        return False


def clear_all_memory(user_id: str = "default") -> dict:
    """Nuclear option — deletes all signals and product memories for a user."""
    if not _DB_AVAILABLE:
        return {"signals_deleted": 0, "products_deleted": 0}
    signals_deleted = 0
    products_deleted = 0
    try:
        signals_deleted = _db_clear_signals(user_id=user_id)
        products_deleted = _db_clear_product_memories(user_id=user_id)
    except Exception as exc:
        _logger.warning("[memory] clear_all_memory error: %s", exc)
    return {"signals_deleted": signals_deleted, "products_deleted": products_deleted}


# ---------------------------------------------------------------------------
# Product filter: apply memory to scored products
# ---------------------------------------------------------------------------

def apply_product_memory_flags(scored_products: list[dict], user_id: str = "default") -> list[dict]:
    """
    Add `memory` field to each product if we have a ProductMemory record for it.
    Products with status=rejected are moved to the bottom.
    Products with status=purchased or returned get a badge.

    Does NOT hide products — user can see them all, just reordered/flagged.
    """
    if not scored_products or not _DB_AVAILABLE:
        return scored_products

    flagged    = []
    pushed_down = []

    for p in scored_products:
        mem = None
        try:
            # Canonical lookup so "iPhone 15" == "Apple iPhone 15" == "iphone15"
            mem = _db_get_product_memory(_canonical_key(p.get("name", "")), user_id=user_id)
        except Exception:
            pass

        if mem:
            p["memory"] = {
                "status":       mem.get("status"),
                "userFeedback": mem.get("userFeedback") or mem.get("user_feedback"),
                "ourScore":     mem.get("ourScore") or mem.get("our_score"),
            }
            if mem.get("status") == "rejected":
                pushed_down.append(p)
            else:
                flagged.append(p)
        else:
            p["memory"] = None
            flagged.append(p)

    return flagged + pushed_down
