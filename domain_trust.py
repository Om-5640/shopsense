"""
Phase 3: Continuous domain trust scoring (0.0–1.0).

Replaces binary trusted/good/unknown with a continuous score while remaining
fully backward-compatible: authority_tier strings are still generated from
score thresholds so existing analyzer prompts work unchanged.

Score composition:
  known domain  = 60% editorial seed + 40% historical reliability
  unknown domain = 30% seed (default) + 70% historical reliability

Thresholds for authority_tier backward compatibility:
  ≥ 0.90  →  "trusted"
  ≥ 0.65  →  "good"
  < 0.65  →  "unknown"
"""

from __future__ import annotations
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Editorial seed scores — static, domain-specific reputation values.
# Add new domains freely. 0.90+ = best-in-class specialist.
# ---------------------------------------------------------------------------

_SEED: dict[str, float] = {
    # Best-in-class measurement / testing specialists
    "rtings.com":            0.98,
    "wirecutter.com":        0.97,
    "notebookcheck.net":     0.96,
    "tomsguide.com":         0.94,
    "techradar.com":         0.93,
    "anandtech.com":         0.93,
    "pcmag.com":             0.92,
    "arstechnica.com":       0.92,
    "theverge.com":          0.91,
    "engadget.com":          0.90,
    "cnet.com":              0.90,
    "soundguys.com":         0.90,
    "displayninja.com":      0.90,
    "laptopmag.com":         0.89,
    "hardwareunboxed.com":   0.89,
    "dxomark.com":           0.88,
    "gsmarena.com":          0.88,
    "whathifi.com":          0.87,
    "consumerreports.org":   0.87,
    "trustedreviews.com":    0.86,
    "expertreviews.co.uk":   0.86,
    "which.co.uk":           0.86,
    "headfonics.com":        0.85,
    "headphonesaddict.com":  0.84,
    "wired.com":             0.84,
    "digitaltrends.com":     0.84,
    "androidauthority.com":  0.83,
    "91mobiles.com":         0.82,
    "gadgets360.com":        0.82,
    "digit.in":              0.81,
    "techpp.com":            0.80,
    "smartprix.com":         0.80,
    "allure.com":            0.80,
    "sleepfoundation.org":   0.82,
    "sleepopolis.com":       0.80,
    "mattressclarity.com":   0.79,
    "runnersworld.com":      0.80,
    "runnerworld.com":       0.80,
    "byrdie.com":            0.78,
    "goodhousekeeping.com":  0.79,
    "menshealth.com":        0.77,
    "womenshealthmag.com":   0.77,
    "forbes.com":            0.75,
    "businessinsider.com":   0.73,
    "health.com":            0.72,
    "sfgate.com":            0.70,
    "today.com":             0.70,
    "nymag.com":             0.74,
    "thestrategist.com":     0.74,
}

_DEFAULT_SEED = 0.50
_TRUSTED_THRESH = 0.90
_GOOD_THRESH = 0.65


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_domain_trust_score(url: str) -> float:
    """
    Return continuous trust score 0.0–1.0 for a URL's domain.

    Combines editorial seed with historical scrape reliability.
    When no scrape history exists, the seed score is used directly so
    known authoritative domains (rtings.com, wirecutter.com, etc.) keep their
    full reputation even before being scraped.
    Never raises.
    """
    try:
        domain = _domain(url)
        if not domain:
            return _DEFAULT_SEED
        seed = _seed_score(domain)
        hist = _get_history(domain)
        if not hist:
            # No history yet — trust the editorial seed entirely
            return seed
        rel = _reliability_from_hist(hist)
        if seed == _DEFAULT_SEED:
            score = 0.30 * seed + 0.70 * rel
        else:
            score = 0.60 * seed + 0.40 * rel
        return round(min(1.0, max(0.0, score)), 3)
    except Exception:
        return _DEFAULT_SEED


def get_authority_tier_from_score(score: float) -> str:
    """Convert trust score to legacy authority_tier string. Backward compatible."""
    if score >= _TRUSTED_THRESH:
        return "trusted"
    if score >= _GOOD_THRESH:
        return "good"
    return "unknown"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _domain(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower()
        return netloc[4:] if netloc.startswith("www.") else netloc
    except Exception:
        return ""


def _seed_score(domain: str) -> float:
    if domain in _SEED:
        return _SEED[domain]
    # Subdomain match: blog.rtings.com → rtings.com score with slight penalty
    for base, score in _SEED.items():
        if domain.endswith("." + base):
            return round(score * 0.95, 3)
    return _DEFAULT_SEED


def _get_history(domain: str) -> list:
    """Fetch scrape history list from domain_blacklist. Returns [] on any failure."""
    try:
        from domain_blacklist import get_history
        return get_history(domain)
    except Exception:
        return []


def _reliability_from_hist(hist: list) -> float:
    """Map success/failure history to [0.30, 0.90] reliability score."""
    if not hist:
        return 0.50
    rate = sum(1 for x in hist if x) / len(hist)
    return round(0.30 + rate * 0.60, 3)
