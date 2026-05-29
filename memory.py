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

import json
import sys
import uuid
from pathlib import Path
from typing import Optional

# Ensure api/ is importable when called from project root
_API_DIR = Path(__file__).parent / "api"
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from agents import run_agent
from embeddings import embed, embed_batch


# ---------------------------------------------------------------------------
# Signal extraction (runs after interview completes)
# ---------------------------------------------------------------------------

_EXTRACT_SYSTEM = """You extract DURABLE user preference signals from a product research interview.

ONLY extract signals that will be EQUALLY RELEVANT in future searches (weeks or months from now).

INCLUDE (durable facts):
- Physical traits: sensitive skin, wears glasses, has flat feet, runs hot, sensitive to fragrance
- Long-term taste: prefers balanced audio, dislikes bass-heavy sound, likes minimal design
- Permanent aversions: allergic to nickel, hates in-ear fit, can't use creams with alcohol
- Lifestyle context: exercises daily, works from home 8+ hrs, commutes by metro
- Body type constraints: narrow feet, wrist under 16cm, large head circumference

DO NOT EXTRACT (transient context):
- Budget/price ("under ₹400", "wants something cheap") — budgets change per purchase
- Current search intent ("looking for skincare now", "needs earbuds for gym")
- Location/region — already stored separately
- Vague preferences ("wants good quality", "likes value for money")
- One-time context that won't apply next month

RULES:
1. "strength": "strong" = certain physical/allergy constraint; "moderate" = clear stated preference; "weak" = soft preference
2. "category_hint": "any" ONLY for facts that apply across all shopping (e.g. "sensitive to fragrances", "has flat feet"). For product-specific facts, use the category (e.g. "skincare", "electronics/earbuds")
3. Rephrase as a compact third-person fact: "Has sensitive, dry skin" not "User said their skin is dry and sensitive"
4. If an interview has nothing durable, return {"signals": []}

Return JSON only: {"signals": [{"type": "preference"|"rejection"|"complaint", "category_hint": "<category or 'any'>", "text": "<concise fact>", "strength": "strong"|"moderate"|"weak"}]}"""


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
    if not qa_history:
        return []

    # Filter [Skipped] entries — they carry no signal worth persisting
    _SKIP_TOKENS = {"[Skipped]", "(skipped)"}
    answered = [e for e in qa_history if e.get("answer", "") not in _SKIP_TOKENS]
    if not answered:
        return []

    qa_text = "\n".join(
        f"Q: {entry.get('question', '')}\nA: {entry.get('answer', '')}"
        for entry in answered
    )
    prompt = f"Category being researched: {category}\n\nInterview transcript:\n{qa_text}"

    try:
        raw = run_agent("signal_extractor", user_prompt=prompt, system=_EXTRACT_SYSTEM)
        from llm_client import _try_repair_json
        data = _try_repair_json(raw)
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict, got {type(data).__name__}")
        signals_raw = data.get("signals", [])
    except Exception as exc:
        print(f"[memory] signal extraction failed (non-fatal): {exc}")
        return []

    if not signals_raw:
        return []

    # Embed all signal texts in one batch call
    texts = [s.get("text", "") for s in signals_raw]
    embeddings = embed_batch(texts)

    saved = []
    try:
        from db import save_signal as _save_signal
    except ImportError:
        print("[memory] db not importable — signals will not be persisted")
        return signals_raw

    for i, sig in enumerate(signals_raw):
        text = sig.get("text", "").strip()
        if not text:
            continue
        sig_id = "sig_" + uuid.uuid4().hex[:16]
        try:
            _save_signal(
                signal_id=sig_id,
                signal_type=sig.get("type", "preference"),
                text=text,
                embedding=embeddings[i],
                category=sig.get("category_hint") or category,
                strength=sig.get("strength", "moderate"),
                source_search_id=source_search_id,
                user_id=user_id,
            )
            saved.append({"id": sig_id, **sig})
        except Exception as exc:
            print(f"[memory] save_signal failed (non-fatal): {exc}")

    print(f"[memory] extracted and saved {len(saved)} signals from interview")
    return saved


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
      - category_hint != current_category   → include only if similarity ≥ min_similarity + 0.15 (tighter = cross-category transfer)
    """
    query_vec = embed(query)
    if query_vec is None:
        return []

    try:
        from db import find_similar_signals
    except ImportError:
        return []

    try:
        raw_results = find_similar_signals(query_vec, k=k * 3, min_similarity=0.0, user_id=user_id)
    except Exception as exc:
        print(f"[memory] find_similar_signals failed (non-fatal): {exc}")
        return []

    filtered = []
    for r in raw_results:
        sim = float(r.get("similarity") or 0.0)
        hint = (r.get("category") or r.get("categoryHint") or "any").lower()
        cat_lc = (current_category or "").lower()

        if hint == "any":
            threshold = min_similarity
        elif hint == cat_lc:
            threshold = max(0.5, min_similarity - 0.1)
        else:
            threshold = min_similarity + 0.15  # cross-category: stricter

        if sim >= threshold:
            filtered.append(r)

    filtered.sort(key=lambda x: -float(x.get("similarity") or 0.0))
    return filtered[:k]


def summarize_user_profile(current_category: Optional[str] = None, user_id: str = "default") -> str:
    """
    Generate a compact text summary of known user preferences.
    Used to inject memory context into rubric generation and interview prompts.
    Returns "" if no signals exist.
    """
    try:
        from db import list_signals
        signals = list_signals(user_id=user_id, limit=50)
    except Exception:
        return ""

    if not signals:
        return ""

    def category_applies(signal_category: str) -> bool:
        hint = (signal_category or "any").lower()
        cat = (current_category or "").lower()
        if hint == "any" or not cat:
            return True
        return hint == cat or cat.startswith(f"{hint}/") or cat.startswith(f"{hint}-")

    relevant = [s for s in signals if category_applies(s.get("category", ""))]
    if not relevant:
        return ""

    strong = [s for s in relevant if s.get("strength") == "strong"]
    moderate = [s for s in relevant if s.get("strength") == "moderate"]

    lines = ["Remembered user preferences (from past searches):"]
    for s in strong[:8]:
        tag = f"[{s.get('signalType', 'preference')}]"
        lines.append(f"  • {tag} {s['text']}")
    for s in moderate[:5]:
        tag = f"[{s.get('signalType', 'preference')}]"
        lines.append(f"  • {tag} {s['text']}")

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
) -> bool:
    """Upsert a product memory record. Returns True on success."""
    try:
        from db import save_product_memory as _save
        _save(product_name, category, status, our_score, user_feedback)
        return True
    except Exception as exc:
        print(f"[memory] save_product_memory failed (non-fatal): {exc}")
        return False


def get_product_memory(product_name: str) -> Optional[dict]:
    try:
        from db import get_product_memory as _get
        return _get(product_name)
    except Exception:
        return None


def list_user_signals(limit: int = 200) -> list[dict]:
    try:
        from db import list_signals
        return list_signals(limit=limit)
    except Exception:
        return []


def list_product_memories(limit: int = 100) -> list[dict]:
    try:
        from db import list_product_memories as _list
        return _list(limit=limit)
    except Exception:
        return []


def delete_product_memory(product_name: str) -> bool:
    try:
        from db import delete_product_memory as _delete
        return _delete(product_name)
    except Exception:
        return False


def delete_signal(signal_id: str) -> bool:
    try:
        from db import delete_signal as _delete
        return _delete(signal_id)
    except Exception:
        return False


def clear_all_memory() -> dict:
    """Nuclear option — deletes all signals and product memories."""
    signals_deleted = 0
    products_deleted = 0
    try:
        from db import clear_signals, clear_product_memories
        signals_deleted = clear_signals()
        products_deleted = clear_product_memories()
    except Exception as exc:
        print(f"[memory] clear_all_memory error: {exc}")
    return {"signals_deleted": signals_deleted, "products_deleted": products_deleted}


# ---------------------------------------------------------------------------
# Product filter: apply memory to scored products
# ---------------------------------------------------------------------------

def apply_product_memory_flags(scored_products: list[dict]) -> list[dict]:
    """
    Add `memory` field to each product if we have a ProductMemory record for it.
    Products with status=rejected are moved to the bottom.
    Products with status=purchased or returned get a badge.

    Does NOT hide products — user can see them all, just reordered/flagged.
    """
    if not scored_products:
        return scored_products

    try:
        from db import get_product_memory as _get
    except ImportError:
        return scored_products

    flagged = []
    pushed_down = []

    for p in scored_products:
        mem = None
        try:
            mem = _get(p.get("name", ""))
        except Exception:
            pass

        if mem:
            p["memory"] = {
                "status": mem.get("status"),
                "userFeedback": mem.get("userFeedback") or mem.get("user_feedback"),
                "ourScore": mem.get("ourScore") or mem.get("our_score"),
            }
            if mem.get("status") == "rejected":
                pushed_down.append(p)
            else:
                flagged.append(p)
        else:
            p["memory"] = None
            flagged.append(p)

    return flagged + pushed_down
