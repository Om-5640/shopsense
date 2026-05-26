"""
Domain blacklist — tracks per-domain scrape failure rates.

Auto-blacklists domains after 3 consecutive failures (403/timeout/etc.)
or a >70% failure rate over the last 5 attempts. Persists to
domain_blacklist.json so known-bad domains are remembered across runs.

Usage:
    from domain_blacklist import is_blacklisted, record_failure, record_success
    if not is_blacklisted(domain):
        try:
            ...scrape...
            record_success(domain)
        except Exception as e:
            record_failure(domain, status_code=403)
"""

import json
import threading
from pathlib import Path

_BLACKLIST_FILE = Path(__file__).parent / "domain_blacklist.json"

# Pre-populated with known-bad domains (paywalls, JS-only, permanent 403s)
_BUILTIN = {
    # Paywalls
    "medium.com", "wired.com", "nytimes.com", "wsj.com", "ft.com",
    "bloomberg.com",
    # Social / video (no article text)
    "youtube.com", "youtu.be", "instagram.com", "tiktok.com",
    "twitter.com", "x.com", "facebook.com", "reddit.com",
    # Product pages (not reviews)
    "amazon.com", "amazon.in", "amazon.co.uk", "amazon.de",
    "flipkart.com", "myntra.com", "snapdeal.com",
    # Consistently 403 in India
    "ndtv.com", "hindustantimes.com", "economictimes.indiatimes.com",
    # JS-only
    "businessinsider.com", "verge.com",
}


class _DomainBlacklist:
    _CONSECUTIVE_THRESH = 3   # auto-blacklist after N consecutive failures
    _RATE_THRESH = 0.70       # auto-blacklist if >70% failure rate
    _RATE_WINDOW = 5          # rolling window size

    def __init__(self):
        self._lock = threading.Lock()
        self._persistent: set[str] = set(_BUILTIN)
        self._history: dict[str, list[bool]] = {}  # domain → [True=ok, False=fail]
        self._load()

    def _load(self):
        try:
            if _BLACKLIST_FILE.exists():
                data = json.loads(_BLACKLIST_FILE.read_text(encoding="utf-8"))
                self._persistent.update(data.get("blacklisted", []))
        except Exception:
            pass

    def _save(self):
        try:
            _BLACKLIST_FILE.write_text(
                json.dumps({"blacklisted": sorted(self._persistent)}, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _norm(self, domain: str) -> str:
        return domain.lower().replace("www.", "").strip("/")

    def is_blacklisted(self, domain: str) -> bool:
        d = self._norm(domain)
        with self._lock:
            return d in self._persistent

    def record_failure(self, domain: str, status_code: int | None = None):
        d = self._norm(domain)
        with self._lock:
            hist = self._history.setdefault(d, [])
            hist.append(False)
            if len(hist) > self._RATE_WINDOW:
                hist[:] = hist[-self._RATE_WINDOW:]

            if d in self._persistent:
                return  # already blacklisted

            # Consecutive failures
            consecutive = 0
            for r in reversed(hist):
                if not r:
                    consecutive += 1
                else:
                    break

            if consecutive >= self._CONSECUTIVE_THRESH:
                print(f"[blacklist] auto-blacklisting {d} ({consecutive} consecutive failures)")
                self._persistent.add(d)
                self._save()
                return

            # Rate-based
            if len(hist) >= self._RATE_WINDOW:
                rate = hist.count(False) / len(hist)
                if rate >= self._RATE_THRESH:
                    print(f"[blacklist] auto-blacklisting {d} ({rate:.0%} failure rate)")
                    self._persistent.add(d)
                    self._save()

    def record_success(self, domain: str):
        d = self._norm(domain)
        with self._lock:
            hist = self._history.setdefault(d, [])
            hist.append(True)
            if len(hist) > self._RATE_WINDOW:
                hist[:] = hist[-self._RATE_WINDOW:]

    def remove(self, domain: str):
        """Manually un-blacklist a domain (for testing / manual override)."""
        d = self._norm(domain)
        with self._lock:
            self._persistent.discard(d)
            self._save()

    def get_all(self) -> set[str]:
        with self._lock:
            return set(self._persistent)


_bl = _DomainBlacklist()


def is_blacklisted(domain: str) -> bool:
    return _bl.is_blacklisted(domain)


def record_failure(domain: str, status_code: int | None = None):
    _bl.record_failure(domain, status_code)


def record_success(domain: str):
    _bl.record_success(domain)


def remove(domain: str):
    _bl.remove(domain)


def get_all() -> set[str]:
    return _bl.get_all()
