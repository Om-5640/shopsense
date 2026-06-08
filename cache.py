"""
Two-tier cache: Redis (primary, optional) + file-based (fallback/always-available).

Tier selection:
  - When REDIS_URL env var is set and the redis package is importable, Redis is
    used as the primary tier (fast, shared across processes).
  - File-based cache is ALWAYS written as a fallback so a Redis restart or
    misconfiguration never loses cached data — the next request will just be
    served from disk instead.
  - Any Redis error (connection failure, serialization error, etc.) is caught
    silently and the code falls through to the file tier without raising.

Per-type TTLs (Redis only):
  - pipeline_result: 86400 s (24 h) — fresh pipeline results wanted daily
  - all other types:  604800 s (7 d)  — same as the file-tier default

File-tier TTL: 7 days for all types (unchanged from before this change).

Public API (unchanged from old cache.py):
    get(cache_type, key)         → value | None
    set(cache_type, key, value)  → None
    purge_expired(max_age_seconds) → int
    cache_backend()              → "redis" | "file"
"""

import logging
import os
import json
import time
import hashlib
from pathlib import Path

_logger = logging.getLogger(__name__)

# ── File-tier constants ────────────────────────────────────────────────────────
CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days

# ── Per-type Redis TTLs ────────────────────────────────────────────────────────
_REDIS_TTL: dict[str, int] = {
    "pipeline_result": 86_400,    # 24 h
}
_REDIS_TTL_DEFAULT = 604_800      # 7 days


# ── Redis client (lazy, optional) ────────────────────────────────────────────

_redis_client = None
_redis_checked = False


def _get_redis():
    """Return a connected redis.Redis instance or None if unavailable."""
    global _redis_client, _redis_checked
    if _redis_checked:
        return _redis_client

    _redis_checked = True
    redis_url = os.environ.get("REDIS_URL", "").strip()
    if not redis_url:
        return None

    try:
        import redis  # type: ignore[import]
        client = redis.Redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=2)
        client.ping()  # confirm connection at startup
        _redis_client = client
        _logger.info("[cache] Redis connected: %s", redis_url.split("@")[-1])
    except Exception as exc:
        _logger.warning("[cache] Redis unavailable (%s) — falling back to file cache", exc)
        _redis_client = None

    return _redis_client


def _redis_key(cache_type: str, key: str) -> str:
    h = hashlib.sha256(f"{cache_type}::{key}".encode()).hexdigest()[:16]
    return f"shopsense:{cache_type}:{h}"


def _redis_ttl(cache_type: str) -> int:
    return _REDIS_TTL.get(cache_type, _REDIS_TTL_DEFAULT)


# ── File-tier helpers ──────────────────────────────────────────────────────────

def _cache_path(cache_type: str, key: str) -> Path:
    h = hashlib.sha256(f"{cache_type}::{key}".encode()).hexdigest()[:16]
    return CACHE_DIR / f"{cache_type}_{h}.json"


def _file_get(cache_type: str, key: str):
    path = _cache_path(cache_type, key)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            entry = json.load(f)
        if time.time() - entry["timestamp"] > CACHE_TTL_SECONDS:
            try:
                path.unlink()
            except Exception:
                pass
            return None
        return entry["value"]
    except Exception:
        try:
            path.unlink()
        except Exception:
            pass
        return None


def _file_set(cache_type: str, key: str, value) -> None:
    path = _cache_path(cache_type, key)
    tmp = path.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"timestamp": time.time(), "value": value}, f)
        tmp.replace(path)
    except Exception as e:
        _logger.warning("[cache] file write failed (non-fatal): %s", e)
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


# ── Public API ────────────────────────────────────────────────────────────────

def get(cache_type: str, key: str):
    """
    Return cached value or None if missing/expired/corrupt.
    Checks Redis first (if available), then falls back to file.
    """
    r = _get_redis()
    if r is not None:
        try:
            raw = r.get(_redis_key(cache_type, key))
            if raw is not None:
                return json.loads(raw)
        except Exception as exc:
            _logger.debug("[cache] Redis get failed (non-fatal): %s", exc)

    return _file_get(cache_type, key)


def set(cache_type: str, key: str, value) -> None:
    """
    Write to cache.
    Always writes to the file tier (guaranteed fallback).
    Also writes to Redis when available.
    """
    # Always persist to file
    _file_set(cache_type, key, value)

    # Best-effort Redis write
    r = _get_redis()
    if r is not None:
        try:
            r.setex(
                _redis_key(cache_type, key),
                _redis_ttl(cache_type),
                json.dumps(value, default=str),
            )
        except Exception as exc:
            _logger.debug("[cache] Redis set failed (non-fatal): %s", exc)


def purge_expired(max_age_seconds: int | None = None) -> int:
    """
    Delete all file-tier cache files older than max_age_seconds.
    Redis manages its own TTL expiry automatically.
    Returns count of deleted files.
    """
    cutoff = max_age_seconds if max_age_seconds is not None else CACHE_TTL_SECONDS
    deleted = 0
    try:
        for p in CACHE_DIR.glob("*.json"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    entry = json.load(f)
                if time.time() - entry.get("timestamp", 0) > cutoff:
                    p.unlink()
                    deleted += 1
            except Exception:
                try:
                    p.unlink()
                    deleted += 1
                except Exception:
                    pass
    except Exception:
        pass
    if deleted:
        _logger.info("[cache] purged %d expired file-cache entries", deleted)
    return deleted


def cache_backend() -> str:
    """Return 'redis' if Redis is the active primary tier, else 'file'."""
    return "redis" if _get_redis() is not None else "file"
