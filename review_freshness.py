"""
Phase 2: Review freshness scoring.

Extracts publication/update dates from raw HTML (before content stripping)
and computes a 0.0–1.0 freshness score using a time-decay curve.

Priority order for date selection:
  dateModified (meta/JSON-LD) > datePublished > <time> element > URL pattern

Decay curve:
  0–6 months    = 1.0
  6–12 months   = 0.9
  1–2 years     = 0.7
  2–3 years     = 0.5
  3+ years      = 0.2

Never discards reviews for age — score is used for ranking only.
Returns 0.5 (neutral) when date is unknown so unknowns don't hurt ranking.
"""

import json
import re
from datetime import datetime, timezone
from typing import Optional

from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_article_date(html: str, url: str = "") -> Optional[str]:
    """
    Extract the most authoritative publication/update date from raw HTML.
    Returns ISO 8601 date string (YYYY-MM-DD) or None.
    Called BEFORE BeautifulSoup strips the HTML.
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
        return _best_date(soup, url)
    except Exception:
        return None


def compute_freshness_score(date_str: Optional[str]) -> float:
    """
    Compute freshness score 0.0–1.0 from an ISO date string (YYYY-MM-DD).
    Returns 0.5 (neutral) when date is absent or unparseable.
    """
    if not date_str:
        return 0.5
    try:
        dt = _parse_iso(date_str)
        if dt is None:
            return 0.5
        now = datetime.now(timezone.utc)
        age_days = max(0, (now - dt).days)
        return _decay(age_days)
    except Exception:
        return 0.5


# ---------------------------------------------------------------------------
# Decay curve
# ---------------------------------------------------------------------------

def _decay(age_days: int) -> float:
    if age_days <= 180:    # 0–6 months
        return 1.0
    if age_days <= 365:    # 6–12 months
        return 0.9
    if age_days <= 730:    # 1–2 years
        return 0.7
    if age_days <= 1095:   # 2–3 years
        return 0.5
    return 0.2             # 3+ years


# ---------------------------------------------------------------------------
# Date extraction from HTML
# ---------------------------------------------------------------------------

# Meta tag lookups ordered by trustworthiness (modified > published)
_META_ATTRS = [
    {"property": "article:modified_time"},
    {"property": "article:published_time"},
    {"name": "lastModified"},
    {"name": "date"},
    {"name": "pubdate"},
    {"itemprop": "dateModified"},
    {"itemprop": "datePublished"},
]

_URL_DATE_RE = re.compile(r"/(\d{4})/(\d{1,2})/(\d{1,2})/")
_ISO_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_SLASH_RE = re.compile(r"(\d{4})/(\d{2})/(\d{2})")


def _best_date(soup: BeautifulSoup, url: str) -> Optional[str]:
    dates: list[datetime] = []

    # 1. Meta tags
    for attrs in _META_ATTRS:
        el = soup.find("meta", attrs)
        if el:
            d = _parse_iso(el.get("content", ""))
            if d:
                dates.append(d)

    # 2. JSON-LD structured data
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            raw = script.string or ""
            obj = json.loads(raw)
            # Handle both single objects and @graph arrays
            items = obj if isinstance(obj, list) else obj.get("@graph", [obj])
            for item in items:
                for key in ("dateModified", "datePublished"):
                    val = item.get(key, "") if isinstance(item, dict) else ""
                    if val:
                        d = _parse_iso(str(val))
                        if d:
                            dates.append(d)
        except Exception:
            pass

    # 3. <time> elements (e.g., <time datetime="2024-03-15">)
    for time_el in soup.find_all("time"):
        val = time_el.get("datetime") or time_el.get_text(strip=True)
        if val:
            d = _parse_iso(str(val))
            if d:
                dates.append(d)

    # 4. URL-embedded date /2024/01/15/
    m = _URL_DATE_RE.search(url)
    if m:
        try:
            d = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
            dates.append(d)
        except ValueError:
            pass

    if not dates:
        return None

    # Return most recent (prefer updated-date over published-date)
    best = max(dates)
    # Reject obviously wrong future dates (more than 30 days ahead)
    now = datetime.now(timezone.utc)
    if (best - now).days > 30:
        dates.remove(best)
        best = max(dates) if dates else None
    if best is None:
        return None
    return best.strftime("%Y-%m-%d")


def _parse_iso(val: str) -> Optional[datetime]:
    if not val or not isinstance(val, str):
        return None
    val = val.strip()

    for pat in (_ISO_RE, _SLASH_RE):
        m = pat.search(val)
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
            except ValueError:
                pass

    # dateutil as optional fallback
    try:
        from dateutil import parser as _dp
        dt = _dp.parse(val)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass

    return None
