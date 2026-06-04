"""
Domain blacklist — tracks per-domain scrape failure rates.

Status-code-aware, time-bounded blacklisting (all bugs fixed):
  403/401 (auth/forbidden)  → strong signal → 7-day ban
  429 (rate-limited)        → soft signal   → 24-hour ban
  500/502/503/timeout       → transient     → 2-hour ban
  unknown failure           → medium signal → 12-hour ban

Scoring: weighted sum over recent attempts.
  Failure weights vary by status code (Bug 2 fix).
  Domain is banned when score drops below -3.0.
  Successes rehabilitate: score +0.5 per success; ban lifted when score ≥ threshold (Bug 3 fix).
  Bans expire automatically — no domain is banned forever (Bug 1 fix).

Disk write happens outside the lock to avoid blocking parallel workers (Bug 5 fix).
Built-in list restricted to true paywalls/social — scrapeable review sites removed (Bug 4 fix).

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
import time
import threading
from pathlib import Path

_BLACKLIST_FILE = Path(__file__).parent / "domain_blacklist.json"

# Permanent blocks: true paywalls, social/video, and pure product pages.
# Scrapeable review sites (wired.com, verge.com, businessinsider.com, medium.com) are
# intentionally excluded — let them fail naturally so Jina/fallback fetchers can still
# reach them (Bug 4 fix: don't hardcode scrapeable sites).
_BUILTIN_PERMANENT: frozenset[str] = frozenset({
    # Hard subscription paywalls
    "wsj.com", "ft.com", "bloomberg.com",
    # Social / video — no article text
    "youtube.com", "youtu.be", "instagram.com", "tiktok.com",
    "twitter.com", "x.com", "facebook.com", "reddit.com",
    # E-commerce product pages — not review content
    "amazon.com", "amazon.in", "amazon.co.uk", "amazon.de",
    "flipkart.com", "myntra.com", "snapdeal.com",
    # Consistently blocked in India with no Jina bypass
    "ndtv.com", "hindustantimes.com", "economictimes.indiatimes.com",
})

# ── Scoring weights by status code (Bug 2 fix: status code now matters) ───────

_FAILURE_WEIGHT: dict[int | str | None, float] = {
    403: -2.0,       # forbidden — strong signal, domain actively blocks scraping
    401: -2.0,       # auth required — same strength
    404: -0.3,       # not found — content issue, not a domain-level block
    429: -0.8,       # rate-limited — notable but temporary
    500: -0.4,       # server error — transient
    502: -0.4,       # bad gateway — transient
    503: -0.4,       # service unavailable — transient
    "timeout": -0.4,
    None: -1.0,      # unknown failure — medium penalty
}
_SUCCESS_WEIGHT = 0.5
_BLACKLIST_THRESHOLD = -3.0  # ban when weighted score falls below this


def _expiry_seconds(status_code: int | str | None) -> float:
    """Return ban duration in seconds based on failure type (Bug 1 fix: time-bounded bans)."""
    if status_code in (403, 401):
        return 7 * 86400.0    # 7 days for auth failures
    if status_code == 429:
        return 86400.0        # 24 hours for rate limits
    if status_code in (500, 502, 503, "timeout"):
        return 7200.0         # 2 hours for transient errors
    return 43200.0            # 12 hours for unknown failures


class _DomainBlacklist:
    _HISTORY_WINDOW = 15  # rolling window for domain_trust.py compatibility

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._permanent: set[str] = set(_BUILTIN_PERMANENT)
        # domain → epoch time when temporary ban expires (Bug 1 fix: no more forever-bans)
        self._blacklisted_until: dict[str, float] = {}
        # domain → status_code that triggered the active ban
        self._ban_reasons: dict[str, int | str | None] = {}
        # domain → weighted reliability score (O1 fix: weighted score, not binary)
        self._scores: dict[str, float] = {}
        # domain → list[bool] for domain_trust.py backward compatibility
        self._history: dict[str, list[bool]] = {}
        self._load()

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            if _BLACKLIST_FILE.exists():
                data = json.loads(_BLACKLIST_FILE.read_text(encoding="utf-8"))
                self._permanent.update(data.get("permanent", []))
                # Legacy format support: old "blacklisted" key → permanent
                self._permanent.update(data.get("blacklisted", []))
                now = time.time()
                for domain, expires_at in data.get("temporary", {}).items():
                    if expires_at > now:  # ignore already-expired bans
                        self._blacklisted_until[domain] = expires_at
        except Exception:
            pass

    def _save(self) -> None:
        """Persist state to disk. MUST be called outside the lock (Bug 5 fix)."""
        try:
            now = time.time()
            custom_permanent = sorted(self._permanent - _BUILTIN_PERMANENT)
            active_temp = {d: exp for d, exp in self._blacklisted_until.items() if exp > now}
            _BLACKLIST_FILE.write_text(
                json.dumps({"permanent": custom_permanent, "temporary": active_temp}, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    # ── Normalisation ──────────────────────────────────────────────────────────

    def _norm(self, domain: str) -> str:
        return domain.lower().replace("www.", "").strip("/")

    # ── Public interface ───────────────────────────────────────────────────────

    def is_blacklisted(self, domain: str) -> bool:
        d = self._norm(domain)
        with self._lock:
            if d in self._permanent:
                return True
            expires = self._blacklisted_until.get(d)
            if expires is None:
                return False
            if time.time() < expires:
                return True
            # Expired — clean up lazily so memory doesn't accumulate (Bug 1 fix)
            del self._blacklisted_until[d]
            self._ban_reasons.pop(d, None)
            return False

    def record_failure(self, domain: str, status_code: int | str | None = None) -> None:
        d = self._norm(domain)
        should_save = False

        with self._lock:
            if d in self._permanent:
                return

            # Update weighted score (O1 + Bug 2 fix)
            weight = _FAILURE_WEIGHT.get(status_code, _FAILURE_WEIGHT[None])
            self._scores[d] = self._scores.get(d, 0.0) + weight

            # Update rolling bool history for domain_trust.py
            hist = self._history.setdefault(d, [])
            hist.append(False)
            if len(hist) > self._HISTORY_WINDOW:
                hist[:] = hist[-self._HISTORY_WINDOW:]

            # If already banned, only upgrade if this is a stronger signal (403/401)
            if d in self._blacklisted_until:
                current_code = self._ban_reasons.get(d)
                if status_code in (403, 401) and current_code not in (403, 401):
                    self._blacklisted_until[d] = time.time() + _expiry_seconds(status_code)
                    self._ban_reasons[d] = status_code
                    should_save = True
                return

            # Check if score crossed the blacklist threshold
            if self._scores[d] < _BLACKLIST_THRESHOLD:
                expiry = _expiry_seconds(status_code)
                self._blacklisted_until[d] = time.time() + expiry
                self._ban_reasons[d] = status_code
                duration_str = (f"{expiry / 3600:.0f}h" if expiry < 7 * 86400 else f"{expiry / 86400:.0f}d")
                print(
                    f"[blacklist] {d} banned for {duration_str} "
                    f"(score={self._scores[d]:.1f}, status={status_code})"
                )
                should_save = True
        # ← lock released BEFORE disk write (Bug 5 fix)
        if should_save:
            self._save()

    def record_success(self, domain: str) -> None:
        d = self._norm(domain)
        should_save = False

        with self._lock:
            if d in self._permanent:
                return

            # Improve score — cap at 0.0 (domains start at 0; successes can't go positive)
            self._scores[d] = min(0.0, self._scores.get(d, 0.0) + _SUCCESS_WEIGHT)

            # Update rolling bool history
            hist = self._history.setdefault(d, [])
            hist.append(True)
            if len(hist) > self._HISTORY_WINDOW:
                hist[:] = hist[-self._HISTORY_WINDOW:]

            # Lift ban if score has recovered above threshold (Bug 3 fix)
            if d in self._blacklisted_until and self._scores[d] >= _BLACKLIST_THRESHOLD:
                print(f"[blacklist] {d} rehabilitated (score={self._scores[d]:.1f})")
                del self._blacklisted_until[d]
                self._ban_reasons.pop(d, None)
                should_save = True
        # ← lock released BEFORE disk write (Bug 5 fix)
        if should_save:
            self._save()

    def remove(self, domain: str) -> None:
        """Manually un-blacklist a domain (for testing / manual override)."""
        d = self._norm(domain)
        with self._lock:
            self._permanent.discard(d)
            self._blacklisted_until.pop(d, None)
            self._ban_reasons.pop(d, None)
            self._scores.pop(d, None)
        self._save()

    def get_all(self) -> set[str]:
        """Return all currently blacklisted domains (permanent + active temporary)."""
        now = time.time()
        with self._lock:
            active_temp = {d for d, exp in self._blacklisted_until.items() if exp > now}
            return set(self._permanent) | active_temp

    def get_ban_info(self, domain: str) -> dict | None:
        """Return ban details, or None if domain is not currently blacklisted."""
        d = self._norm(domain)
        with self._lock:
            if d in self._permanent:
                return {"type": "permanent", "reason": "built-in or manually added"}
            expires = self._blacklisted_until.get(d)
            if expires and time.time() < expires:
                return {
                    "type": "temporary",
                    "expires_at": expires,
                    "expires_in_s": max(0.0, expires - time.time()),
                    "status_code": self._ban_reasons.get(d),
                    "score": self._scores.get(d, 0.0),
                }
            return None


_bl = _DomainBlacklist()

# ── Public module API ─────────────────────────────────────────────────────────

def is_blacklisted(domain: str) -> bool:
    return _bl.is_blacklisted(domain)


def record_failure(domain: str, status_code: int | str | None = None) -> None:
    _bl.record_failure(domain, status_code)


def record_success(domain: str) -> None:
    _bl.record_success(domain)


def remove(domain: str) -> None:
    _bl.remove(domain)


def get_all() -> set[str]:
    return _bl.get_all()


def get_ban_info(domain: str) -> dict | None:
    """Return ban details for a domain (type, expiry, score, reason). None if not banned."""
    return _bl.get_ban_info(domain)


def get_history(domain: str) -> list[bool]:
    """Return scrape history as list[bool] (True=success). Used by domain_trust.py."""
    d = _bl._norm(domain)
    with _bl._lock:
        return list(_bl._history.get(d, []))
