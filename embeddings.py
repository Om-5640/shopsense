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
import os
import hashlib
import requests
from typing import Optional
from dotenv import load_dotenv

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
            params={"key": GEMINI_API_KEY},
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
_local_model_lock = None


def _embed_local(text: str) -> Optional[list[float]]:
    """Use sentence-transformers locally (CPU). Lazy-loads on first call."""
    global _local_model, _local_model_lock
    try:
        import threading
        if _local_model_lock is None:
            _local_model_lock = threading.Lock()
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
# Public API
# ---------------------------------------------------------------------------

def embed(text: str) -> Optional[list[float]]:
    """Return an embedding vector for `text`. Tries Gemini → Cohere → HF → local."""
    if not text.strip():
        return None

    ck = _key(text)
    cached = cache.get(_CACHE_TYPE, ck)
    if cached is not None:
        return cached

    for provider_fn, name in [
        (_embed_gemini, "gemini"),
        (_embed_cohere, "cohere"),
        (_embed_huggingface, "huggingface"),
        (_embed_local, "local"),
    ]:
        vec = provider_fn(text)
        if vec:
            cache.set(_CACHE_TYPE, ck, vec)
            return vec

    _logger.warning("[embeddings] all providers failed — returning None")
    return None


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

    # Try Gemini batch first (most efficient)
    if GEMINI_API_KEY:
        for chunk_start in range(0, len(uncached_texts), 100):
            chunk = uncached_texts[chunk_start: chunk_start + 100]
            chunk_idx = uncached_idx[chunk_start: chunk_start + 100]
            try:
                resp = requests.post(
                    _BATCH_URL,
                    params={"key": GEMINI_API_KEY},
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
                    if vec:
                        idx = chunk_idx[j]
                        results[idx] = vec
                        cache.set(_CACHE_TYPE, _key(chunk[j]), vec)
                # Remove successfully embedded items from uncached lists, keeping both in sync
                succeeded = {chunk_idx[j] for j, emb in enumerate(resp.json().get("embeddings", [])) if emb.get("values")}
                surviving = [(idx, txt) for idx, txt in zip(uncached_idx, uncached_texts) if idx not in succeeded]
                uncached_idx = [p[0] for p in surviving]
                uncached_texts = [p[1] for p in surviving]
                continue
            except Exception as exc:
                _logger.warning("[embeddings] Gemini batch failed: %s", exc)
                break

    # Fall back to serial embed() for anything still uncached
    for i, text in zip(uncached_idx, uncached_texts):
        if results[i] is None:
            results[i] = embed(text)

    return results


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [0.0, 1.0]. Returns 0.0 on bad input."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = sum(x * x for x in a) ** 0.5
    mag_b = sum(x * x for x in b) ** 0.5
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (mag_a * mag_b)))
