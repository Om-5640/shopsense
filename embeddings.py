"""
Text embedding service with multi-provider fallback.

Provider chain (first available wins):
  1. Gemini  — gemini-embedding-001, 3072 dims (best quality, needs GEMINI_API_KEY)
  2. Cohere  — embed-english-light-v3.0, 384 dims (fast free tier, needs COHERE_API_KEY)
  3. HuggingFace Inference API — sentence-transformers/all-MiniLM-L6-v2, 384 dims (needs HF_API_KEY)
  4. Local sentence-transformers — all-MiniLM-L6-v2, 384 dims (CPU, no API key needed)

Caches by SHA256 of input text — repeated embeddings cost nothing.
Falls back gracefully; returns None only if every provider fails.
"""

import logging
import math
import os
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

load_dotenv()

GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY", "")
COHERE_API_KEY  = os.environ.get("COHERE_API_KEY", "")
HF_API_KEY      = os.environ.get("HF_API_KEY", "")

_EMBED_MODEL = "gemini-embedding-001"
_EMBED_URL = (
    f"https://generativelanguage.googleapis.com/v1beta"
    f"/models/{_EMBED_MODEL}:embedContent"
)
_BATCH_URL = (
    f"https://generativelanguage.googleapis.com/v1beta"
    f"/models/{_EMBED_MODEL}:batchEmbedContents"
)
_CACHE_TYPE = "embedding"
_MAX_TEXT_CHARS = 8000


def _key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------

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
        # HF returns list of floats directly for sentence-transformers
        if isinstance(result, list) and result and isinstance(result[0], float):
            return result
        # Some models return nested list
        if isinstance(result, list) and result and isinstance(result[0], list):
            return result[0]
        return None
    except Exception as exc:
        _logger.warning("[embeddings] HuggingFace failed: %s", exc)
        return None


_local_model = None
_local_model_lock = threading.Lock()   # module-level — no lazy init race (Bug 2 fix)


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
        return None  # sentence-transformers not installed
    except Exception as exc:
        _logger.warning("[embeddings] local model failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# In-flight dedup — prevents 15 parallel thread-summarizers from each making
# a separate API call for the same query text (they all call embed(query) at once).
# Pattern mirrors llm_clients.py: first caller does the work, others wait and reuse.
# ---------------------------------------------------------------------------

_inflight_lock = threading.Lock()
_inflight: dict[str, threading.Event] = {}    # ck → event signalled when result is ready
_inflight_results: dict[str, Optional[list[float]]] = {}  # ck → computed vector


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def embed(text: str) -> Optional[list[float]]:
    """Return an embedding vector for `text`. Tries Gemini → Cohere → HF → local.

    In-flight dedup: if N threads call embed() with the same text simultaneously,
    only the first thread makes the API call; the rest block on an Event and reuse
    the result — zero duplicate API calls.
    """
    if not text.strip():
        return None

    ck = _key(text)

    # Fast path — file cache hit (most common case after first call)
    cached = cache.get(_CACHE_TYPE, ck)
    if cached is not None:
        return cached

    # In-flight dedup: check whether another thread is already computing this vector
    with _inflight_lock:
        if ck in _inflight:
            event = _inflight[ck]
            is_leader = False
        else:
            event = threading.Event()
            _inflight[ck] = event
            is_leader = True

    if not is_leader:
        # Wait for the leader thread to finish, then read its result
        event.wait(timeout=60)
        with _inflight_lock:
            result = _inflight_results.get(ck)
        return result

    # Leader: compute the vector
    vec: Optional[list[float]] = None
    try:
        for provider_fn, name in [
            (_embed_gemini, "gemini"),
            (_embed_cohere, "cohere"),
            (_embed_huggingface, "huggingface"),
            (_embed_local, "local"),
        ]:
            vec = provider_fn(text)
            if vec is not None:   # explicit None check — empty list is a valid (edge-case) result (Bug 5 fix)
                cache.set(_CACHE_TYPE, ck, vec)
                break

        if vec is None:
            _logger.warning("[embeddings] all providers failed — returning None")
    finally:
        # Always signal waiters and clean up, even on exception
        with _inflight_lock:
            _inflight_results[ck] = vec
            event.set()
            del _inflight[ck]
        # Clean up result after a short grace period (waiters have already read it)
        # We leave it in _inflight_results briefly; it's keyed by SHA256 so
        # a second wave of concurrent callers will hit the file cache instead.
        # Remove to prevent unbounded growth (the file cache is the durable store).
        threading.Timer(2.0, lambda: _inflight_results.pop(ck, None)).start()

    return vec


def embed_batch(texts: list[str]) -> list[Optional[list[float]]]:
    """
    Embed up to 100 texts. Cache hits are resolved locally; only uncached texts hit APIs.
    Gemini supports native batching; other providers fall back to serial embed() calls.
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
        hit = cache.get(_CACHE_TYPE, ck)
        if hit is not None:
            results[i] = hit
        else:
            uncached_idx.append(i)
            uncached_texts.append(text)

    if not uncached_texts:
        return results

    # Try Gemini batch first (most efficient).
    # Process in chunks of 100 (API limit). Range is computed from the original list
    # and never mutated inside the loop — the serial fallback below handles any misses.
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
                embeddings = resp.json().get("embeddings", [])   # parse once (Bug 3 fix)
                for j, emb in enumerate(embeddings):
                    vec = emb.get("values")
                    if vec is not None and j < len(chunk_idx):
                        idx = chunk_idx[j]
                        results[idx] = vec
                        cache.set(_CACHE_TYPE, _key(chunk[j]), vec)
            except Exception as exc:
                _logger.warning("[embeddings] Gemini batch failed: %s", exc)
                break

    # Fall back to serial embed() for anything still uncached
    for i, text in zip(uncached_idx, uncached_texts):
        if results[i] is None:
            results[i] = embed(text)

    return results


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [0.0, 1.0]. Returns 0.0 on bad input.

    Uses numpy when available (~10× faster for 3072-dim Gemini vectors);
    falls back to math.sqrt-based pure Python otherwise.
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
