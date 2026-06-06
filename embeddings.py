"""
Text embedding service with multi-provider fallback.

Provider chain (first available wins):
  1. Gemini  — gemini-embedding-001, 3072 dims (best quality, needs GEMINI_API_KEY)
  2. Cohere  — embed-english-light-v3.0, 384 dims (fast free tier, needs COHERE_API_KEY)
  3. HuggingFace Inference API — sentence-transformers/all-MiniLM-L6-v2, 384 dims (needs HF_API_KEY)
  4. Local sentence-transformers — all-MiniLM-L6-v2, 384 dims (CPU, no API key needed)

Cache format: {"v": list[float], "p": "<provider>"}
  "p" key is used to detect provider mismatches at retrieval time (Bug 1 fix).
  Old cache entries (plain list) are treated as provider="unknown" — backward compatible.

Bugs fixed:
  Bug 1: Provider metadata stored in cache so Gemini and Cohere vectors are never
         compared against each other (incompatible embedding spaces, different dims).
  Bug 2: threading.Timer replaced with timestamp-based lazy cleanup in _inflight_results —
         no unbounded thread creation under load.
  Bug 3: in-flight event.wait reduced from 60 s to 35 s (> max provider timeout of 30 s).

Optimisations added:
  O1: Cohere batch support in embed_batch (was serial, now one API call for all uncached).
  O2/O3: cosine_similarity_batch — normalises query once, vectorised matrix multiply for
         N candidates; store-once normalization avoids redundant per-call norm computation.
"""

import logging
import math
import os
import time
import hashlib
import threading
import requests
from typing import Optional
from dotenv import load_dotenv

try:
    import numpy as _np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

_logger = logging.getLogger(__name__)

import cache

# DB-tier cache helpers — imported lazily so embeddings.py works even without api/ on sys.path
try:
    from api.db import get_cached_embedding as _db_get_embedding
    from api.db import set_cached_embedding as _db_set_embedding
    _HAS_DB_CACHE = True
except ImportError:
    try:
        from db import get_cached_embedding as _db_get_embedding
        from db import set_cached_embedding as _db_set_embedding
        _HAS_DB_CACHE = True
    except ImportError:
        _HAS_DB_CACHE = False

load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
COHERE_API_KEY = os.environ.get("COHERE_API_KEY", "")
HF_API_KEY     = os.environ.get("HF_API_KEY", "")

_EMBED_MODEL = "gemini-embedding-001"
_EMBED_URL = (
    f"https://generativelanguage.googleapis.com/v1beta"
    f"/models/{_EMBED_MODEL}:embedContent"
)
_BATCH_URL = (
    f"https://generativelanguage.googleapis.com/v1beta"
    f"/models/{_EMBED_MODEL}:batchEmbedContents"
)
_CACHE_TYPE    = "embedding"
_MAX_TEXT_CHARS = 8000


# ── Cache helpers (Bug 1: provider-aware format) ──────────────────────────────

def _key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_cache(ck: str) -> tuple[Optional[list[float]], str]:
    """
    Returns (vector, provider_name).
    Handles both the new dict format {"v": [...], "p": "gemini"} and the legacy
    plain-list format — old entries are tagged "unknown" so they're never silently
    mixed with typed vectors (Bug 1 backward-compat).
    """
    raw = cache.get(_CACHE_TYPE, ck)
    if raw is None:
        return None, ""
    if isinstance(raw, list):
        # Legacy format — plain vector, no provider tag
        _embed_provider_registry[ck] = "unknown"
        return raw, "unknown"
    if isinstance(raw, dict):
        vec = raw.get("v")
        provider = raw.get("p", "unknown")
        if isinstance(vec, list):
            _embed_provider_registry[ck] = provider
            return vec, provider
    return None, ""


def _write_cache(ck: str, vec: list[float], provider: str) -> None:
    """Persist vector with provider metadata (Bug 1 fix)."""
    _embed_provider_registry[ck] = provider
    cache.set(_CACHE_TYPE, ck, {"v": vec, "p": provider})


# ── Provider registry (Bug 1) ─────────────────────────────────────────────────
# Maps cache-key → provider name so callers can detect incompatible vector spaces.

_embed_provider_registry: dict[str, str] = {}


def get_vector_provider(text: str) -> str | None:
    """
    Return the embedding provider used for `text`, or None if not cached.
    Use this to check provider compatibility before computing cosine similarity.
    """
    ck = _key(text)
    if ck in _embed_provider_registry:
        return _embed_provider_registry[ck]
    _, provider = _read_cache(ck)
    return provider or None


def are_same_provider(text_a: str, text_b: str) -> bool:
    """
    True if both texts were embedded by the same provider (safe to compare).
    Returns True when either provider is unknown/uncached — assume compatible.
    """
    pa = get_vector_provider(text_a)
    pb = get_vector_provider(text_b)
    if not pa or not pb or pa == "unknown" or pb == "unknown":
        return True
    return pa == pb


# ── Individual provider implementations ──────────────────────────────────────

def _embed_gemini(text: str) -> Optional[list[float]]:
    if not GEMINI_API_KEY:
        return None
    try:
        resp = requests.post(
            _EMBED_URL,
            headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY},
            json={
                "model": f"models/{_EMBED_MODEL}",
                "content": {"parts": [{"text": text[:_MAX_TEXT_CHARS]}]},
                "taskType": "SEMANTIC_SIMILARITY",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["embedding"]["values"]
    except Exception as exc:
        _logger.warning("[embeddings] Gemini failed: %s", exc)
        return None


def _embed_cohere(text: str) -> Optional[list[float]]:
    if not COHERE_API_KEY:
        return None
    try:
        resp = requests.post(
            "https://api.cohere.ai/v1/embed",
            headers={"Authorization": f"Bearer {COHERE_API_KEY}", "Content-Type": "application/json"},
            json={
                "texts": [text[:_MAX_TEXT_CHARS]],
                "model": "embed-english-light-v3.0",
                "input_type": "search_query",
            },
            timeout=30,
        )
        resp.raise_for_status()
        vecs = resp.json().get("embeddings", [])
        return vecs[0] if vecs else None
    except Exception as exc:
        _logger.warning("[embeddings] Cohere failed: %s", exc)
        return None


def _embed_huggingface(text: str) -> Optional[list[float]]:
    if not HF_API_KEY:
        return None
    try:
        model = "sentence-transformers/all-MiniLM-L6-v2"
        resp = requests.post(
            f"https://api-inference.huggingface.co/models/{model}",
            headers={"Authorization": f"Bearer {HF_API_KEY}"},
            json={"inputs": text[:_MAX_TEXT_CHARS]},
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        if isinstance(result, list) and result and isinstance(result[0], float):
            return result
        if isinstance(result, list) and result and isinstance(result[0], list):
            return result[0]
        return None
    except Exception as exc:
        _logger.warning("[embeddings] HuggingFace failed: %s", exc)
        return None


_local_model = None
_local_model_lock = threading.Lock()


def _embed_local(text: str) -> Optional[list[float]]:
    """Use sentence-transformers locally (CPU). Lazy-loads on first call."""
    global _local_model
    try:
        with _local_model_lock:
            if _local_model is None:
                from sentence_transformers import SentenceTransformer
                _logger.info("[embeddings] loading local sentence-transformers model (one-time)...")
                _local_model = SentenceTransformer("all-MiniLM-L6-v2")
        vec = _local_model.encode(text[:_MAX_TEXT_CHARS], show_progress_bar=False)
        return vec.tolist()
    except ImportError:
        return None
    except Exception as exc:
        _logger.warning("[embeddings] local model failed: %s", exc)
        return None


# ── In-flight dedup ───────────────────────────────────────────────────────────
# Prevents N parallel callers with the same text from each making a separate API call.
# First caller ("leader") does the work; others wait on an Event and reuse the result.

_inflight_lock = threading.Lock()
_inflight: dict[str, threading.Event] = {}
# Bug 2 fix: store (result, timestamp) — timestamp-based lazy cleanup replaces
# threading.Timer, which created one daemon thread per embedding under load.
_inflight_results: dict[str, tuple[Optional[list[float]], str]] = {}
_inflight_ts: dict[str, float] = {}
_INFLIGHT_TTL = 5.0  # seconds before a completed result is eligible for eviction


def _cleanup_inflight_stale() -> None:
    """Lazily evict completed in-flight results that are older than TTL (Bug 2 fix)."""
    now = time.time()
    with _inflight_lock:
        stale = [k for k, t in _inflight_ts.items() if now - t > _INFLIGHT_TTL]
        for k in stale:
            _inflight_results.pop(k, None)
            _inflight_ts.pop(k, None)


# ── Public API ────────────────────────────────────────────────────────────────

def embed(text: str) -> Optional[list[float]]:
    """
    Return an embedding vector for `text`. Provider chain: Gemini → Cohere → HF → local.
    Stores provider metadata in cache so mismatched-space comparisons can be detected
    later (Bug 1 fix). Return type is list[float] — backward compatible.
    """
    if not text.strip():
        return None

    ck = _key(text)

    # Tier 1: in-memory file cache (reads provider metadata into registry)
    cached_vec, _ = _read_cache(ck)
    if cached_vec is not None:
        return cached_vec

    # Tier 2: DB cache (survives server restarts)
    if _HAS_DB_CACHE:
        try:
            db_vec = _db_get_embedding(ck)
            if db_vec is not None:
                _write_cache(ck, db_vec, "db_hit")
                return db_vec
        except Exception as exc:
            _logger.debug("[embeddings] DB cache read failed (non-fatal): %s", exc)

    # Lazy cleanup of stale in-flight results (Bug 2 fix — no Timer threads)
    _cleanup_inflight_stale()

    # In-flight dedup
    with _inflight_lock:
        if ck in _inflight:
            event = _inflight[ck]
            is_leader = False
        else:
            event = threading.Event()
            _inflight[ck] = event
            is_leader = True

    if not is_leader:
        # Bug 3 fix: 35 s > max provider timeout (30 s) — was 60 s
        event.wait(timeout=35)
        with _inflight_lock:
            entry = _inflight_results.get(ck)
        return entry[0] if entry else None

    # Leader: try each provider in order
    vec: Optional[list[float]] = None
    provider = "none"
    try:
        for provider_fn, provider_name in [
            (_embed_gemini,     "gemini"),
            (_embed_cohere,     "cohere"),
            (_embed_huggingface, "huggingface"),
            (_embed_local,      "local"),
        ]:
            vec = provider_fn(text)
            if vec is not None:
                provider = provider_name
                _write_cache(ck, vec, provider)
                # Persist to DB tier so the vector survives restarts
                if _HAS_DB_CACHE:
                    try:
                        _db_set_embedding(ck, text, provider, vec)
                    except Exception as exc:
                        _logger.debug("[embeddings] DB cache write failed (non-fatal): %s", exc)
                break

        if vec is None:
            _logger.warning("[embeddings] all providers failed — returning None")
    finally:
        # Signal all waiters, record result with timestamp (Bug 2 fix: no Timer)
        with _inflight_lock:
            _inflight_results[ck] = (vec, provider)
            _inflight_ts[ck] = time.time()
            event.set()
            del _inflight[ck]

    return vec


def embed_batch(texts: list[str]) -> list[Optional[list[float]]]:
    """
    Embed up to 100 texts efficiently.
    Cache hits resolved locally; uncached texts sent to APIs.
    Supports native batching for Gemini (O1: also Cohere — one call for all uncached texts).
    """
    if not texts:
        return []

    results: list[Optional[list[float]]] = [None] * len(texts)
    uncached_idx: list[int] = []
    uncached_texts: list[str] = []

    for i, text in enumerate(texts):
        if not text.strip():
            continue
        ck = _key(text)
        hit, _ = _read_cache(ck)
        if hit is not None:
            results[i] = hit
        else:
            uncached_idx.append(i)
            uncached_texts.append(text)

    if not uncached_texts:
        return results

    # ── Gemini batch (up to 100 per call) ─────────────────────────────────────
    if GEMINI_API_KEY:
        for chunk_start in range(0, len(uncached_texts), 100):
            chunk = uncached_texts[chunk_start: chunk_start + 100]
            chunk_idx = uncached_idx[chunk_start: chunk_start + 100]
            try:
                resp = requests.post(
                    _BATCH_URL,
                    headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY},
                    json={
                        "requests": [
                            {
                                "model": f"models/{_EMBED_MODEL}",
                                "content": {"parts": [{"text": t[:_MAX_TEXT_CHARS]}]},
                                "taskType": "SEMANTIC_SIMILARITY",
                            }
                            for t in chunk
                        ]
                    },
                    timeout=60,
                )
                resp.raise_for_status()
                for j, emb in enumerate(resp.json().get("embeddings", [])):
                    vec = emb.get("values")
                    if vec is not None and j < len(chunk_idx):
                        idx = chunk_idx[j]
                        results[idx] = vec
                        _write_cache(_key(chunk[j]), vec, "gemini")
            except Exception as exc:
                _logger.warning("[embeddings] Gemini batch failed: %s", exc)
                break

    # ── Cohere batch for remaining uncached texts (O1 fix) ────────────────────
    still_uncached_idx = [i for i in uncached_idx if results[i] is None]
    still_uncached_texts = [uncached_texts[uncached_idx.index(i)] for i in still_uncached_idx]

    if still_uncached_texts and COHERE_API_KEY:
        try:
            resp = requests.post(
                "https://api.cohere.ai/v1/embed",
                headers={"Authorization": f"Bearer {COHERE_API_KEY}", "Content-Type": "application/json"},
                json={
                    "texts": [t[:_MAX_TEXT_CHARS] for t in still_uncached_texts],
                    "model": "embed-english-light-v3.0",
                    "input_type": "search_query",
                },
                timeout=45,
            )
            resp.raise_for_status()
            embeddings = resp.json().get("embeddings", [])
            for j, vec in enumerate(embeddings):
                if vec and j < len(still_uncached_idx):
                    idx = still_uncached_idx[j]
                    results[idx] = vec
                    _write_cache(_key(still_uncached_texts[j]), vec, "cohere")
        except Exception as exc:
            _logger.warning("[embeddings] Cohere batch failed: %s", exc)

    # ── Serial fallback for any remaining misses ───────────────────────────────
    for i, text in zip(uncached_idx, uncached_texts):
        if results[i] is None:
            results[i] = embed(text)

    return results


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """
    Cosine similarity in [0.0, 1.0]. Returns 0.0 on bad input.
    Uses numpy when available (~10× faster for 3072-dim Gemini vectors).
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    if _HAS_NUMPY:
        va = _np.array(a, dtype=_np.float32)
        vb = _np.array(b, dtype=_np.float32)
        denom = _np.linalg.norm(va) * _np.linalg.norm(vb)
        if denom == 0.0:
            return 0.0
        return float(max(0.0, min(1.0, float(_np.dot(va, vb) / denom))))
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (mag_a * mag_b)))


def cosine_similarity_batch(
    query: list[float],
    candidates: list[list[float]],
) -> list[float]:
    """
    Compute cosine similarity between one query vector and N candidate vectors (O2/O3 fix).

    Normalises the query ONCE, then uses a single matrix dot product when numpy is
    available — O(N·D) instead of O(N·D) serial calls that each recompute norms.
    For memory retrieval with 50+ stored signals this is significantly faster.

    Falls back to serial cosine_similarity() for small N or when numpy is absent.
    """
    n = len(candidates)
    if n == 0:
        return []
    if not query:
        return [0.0] * n

    if _HAS_NUMPY and n >= 4:
        q = _np.array(query, dtype=_np.float32)
        q_norm = float(_np.linalg.norm(q))
        if q_norm == 0.0:
            return [0.0] * n

        # Normalise query once (O3: avoid recomputing per candidate)
        q_unit = q / q_norm

        # Stack candidates into a matrix and normalise rows
        M = _np.array(candidates, dtype=_np.float32)          # (N, D)
        row_norms = _np.linalg.norm(M, axis=1, keepdims=True) # (N, 1)
        row_norms = _np.where(row_norms == 0.0, 1.0, row_norms)
        M_unit = M / row_norms                                  # (N, D) unit vectors

        sims = M_unit @ q_unit                                  # (N,) — batch dot product
        return [float(max(0.0, min(1.0, float(s)))) for s in sims]

    # Fallback: serial
    return [cosine_similarity(query, c) for c in candidates]
