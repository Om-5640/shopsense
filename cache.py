"""
Simple file-based cache with 7-day expiry.
Caches by SHA256 of (cache_type, key).
"""

import logging
import os
import json
import time
import hashlib
from pathlib import Path

_logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days


def _cache_path(cache_type: str, key: str) -> Path:
    h = hashlib.sha256(f"{cache_type}::{key}".encode()).hexdigest()[:16]
    return CACHE_DIR / f"{cache_type}_{h}.json"


def get(cache_type: str, key: str):
    """Returns cached value or None if missing/expired/corrupt."""
    path = _cache_path(cache_type, key)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            entry = json.load(f)
        if time.time() - entry["timestamp"] > CACHE_TTL_SECONDS:
            # Delete expired file so cache directory doesn't fill with stale entries
            try:
                path.unlink()
            except Exception:
                pass
            return None
        return entry["value"]
    except Exception:
        try:
            path.unlink()  # delete corrupt file
        except Exception:
            pass
        return None


def set(cache_type: str, key: str, value):
    """Write to cache. Silently skips if disk write fails."""
    path = _cache_path(cache_type, key)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"timestamp": time.time(), "value": value}, f)
    except Exception as e:
        _logger.warning("[cache] write failed (non-fatal): %s", e)


def purge_expired(max_age_seconds: int | None = None) -> int:
    """
    Delete all cache files older than max_age_seconds (default: CACHE_TTL_SECONDS).
    Returns count of deleted files.
    Call periodically (e.g., at server startup) to prevent unbounded disk growth.
    """
    cutoff = max_age_seconds if max_age_seconds is not None else CACHE_TTL_SECONDS
    deleted = 0
    try:
        for p in CACHE_DIR.glob("*.json"):
            try:
                stat = p.stat()
                if time.time() - stat.st_mtime > cutoff:
                    p.unlink()
                    deleted += 1
            except Exception:
                pass
    except Exception:
        pass
    if deleted:
        _logger.info("[cache] purged %d expired cache files", deleted)
    return deleted
