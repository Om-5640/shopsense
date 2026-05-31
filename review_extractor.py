"""
Phase 5: Structured review extraction from raw article text.

Extracts pros, cons, verdict, rating, best_for, not_for, mentioned_price
using regex/heuristics on plain text. Zero LLM calls — fast and always available.

Raw content is NEVER removed. This is purely additive metadata.
Returns an empty structure on any failure — never raises.
"""

import re
from typing import Optional


def extract_review_structure(content: str, url: str = "") -> dict:
    """
    Extract structured review fields from plain article text.

    Returns dict with keys: pros, cons, verdict, rating, best_for, not_for, mentioned_price.
    All keys always present; values are None / [] when not found.
    """
    try:
        return _extract(content)
    except Exception:
        return _empty()


def _empty() -> dict:
    return {
        "pros": [],
        "cons": [],
        "verdict": None,
        "rating": None,
        "best_for": [],
        "not_for": [],
        "mentioned_price": None,
    }


# ---------------------------------------------------------------------------
# Rating
# ---------------------------------------------------------------------------

_RATING_PATS = [
    re.compile(r"\b(\d+(?:\.\d)?)\s*/\s*10\b"),
    re.compile(r"\b(\d+(?:\.\d)?)\s*/\s*5\b"),
    re.compile(r"\b(\d+(?:\.\d)?)\s+out\s+of\s+(?:10|5)\b", re.IGNORECASE),
    re.compile(r"(?:score|rating|verdict)\s*:?\s*(\d+(?:\.\d)?)\s*/\s*(?:10|5)\b", re.IGNORECASE),
]


def _find_rating(text: str) -> Optional[float]:
    for pat in _RATING_PATS:
        m = pat.search(text)
        if m:
            try:
                raw = m.group(0)
                val = float(m.group(1))
                # Normalize /5 scale to /10
                if "/5" in raw or "out of 5" in raw.lower():
                    val = val * 2
                return round(val, 1)
            except (ValueError, IndexError):
                continue
    return None


# ---------------------------------------------------------------------------
# Price
# ---------------------------------------------------------------------------

_PRICE_PAT = re.compile(r"([$£€₹¥])\s*(\d[\d,]{1,6}(?:\.\d{2})?)")


def _find_price(text: str) -> Optional[str]:
    m = _PRICE_PAT.search(text)
    if m:
        return f"{m.group(1)}{m.group(2)}"
    return None


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

_VERDICT_PAT = re.compile(
    r"(?:verdict|bottom\s+line|our\s+verdict|final\s+(?:thoughts?|verdict|word|take)|"
    r"in\s+summary|conclusion|overall\s+impression)\s*[:\-–]\s*([^\n]{20,600})",
    re.IGNORECASE,
)


def _find_verdict(text: str) -> Optional[str]:
    m = _VERDICT_PAT.search(text)
    if m:
        v = m.group(1).strip()
        return v[:400] if v else None
    return None


# ---------------------------------------------------------------------------
# Pros / Cons
# ---------------------------------------------------------------------------

_PROS_HEADERS = [
    "pros", "what we like", "what i like", "advantages", "the good",
    "strengths", "positives", "upsides",
]
_CONS_HEADERS = [
    "cons", "what we don't like", "what we dislike", "what i don't like",
    "disadvantages", "the bad", "weaknesses", "drawbacks", "negatives", "downsides",
]

_BULLET_STRIP = re.compile(r"^[\-•·✓✔✗✘×+★>\d\.]+\s*")


def _extract_section(text: str, headers: list[str], stop_headers: list[str]) -> list[str]:
    """
    Find a labeled section and grab following lines until a stop header or
    two consecutive blank lines.  Works on both bullet-char and plain-line formats
    (BeautifulSoup strips bullet chars from <li> elements).
    """
    header_re = re.compile(
        r"^\s*(?:" + "|".join(re.escape(h) for h in headers) + r")\s*[:\-–]?\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    stop_re = re.compile(
        r"^\s*(?:" + "|".join(re.escape(h) for h in stop_headers) + r")\b",
        re.IGNORECASE | re.MULTILINE,
    )

    hm = header_re.search(text)
    if not hm:
        return []

    start = hm.end()
    sm = stop_re.search(text, start)
    section = text[start : sm.start() if sm else start + 1200]

    items: list[str] = []
    blanks = 0
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped:
            blanks += 1
            if blanks >= 2:
                break
            continue
        blanks = 0
        clean = _BULLET_STRIP.sub("", stripped).strip()
        if 5 < len(clean) < 200:
            items.append(clean)

    return items[:10]


def _find_pros(text: str) -> list[str]:
    return _extract_section(text, _PROS_HEADERS, _CONS_HEADERS + ["verdict", "conclusion", "bottom line"])


def _find_cons(text: str) -> list[str]:
    return _extract_section(text, _CONS_HEADERS, _PROS_HEADERS + ["verdict", "conclusion", "bottom line"])


# ---------------------------------------------------------------------------
# Best-for / Not-for
# ---------------------------------------------------------------------------

_BEST_FOR_PAT = re.compile(
    r"(?:best\s+for|ideal\s+for|who\s+(?:should\s+buy|it'?s?\s+for)|great\s+for|perfect\s+for)"
    r"\s*[:\-–]?\s*([^\n.]{10,200})",
    re.IGNORECASE,
)

_NOT_FOR_PAT = re.compile(
    r"(?:not\s+(?:for|ideal\s+for|suited\s+for)|who\s+(?:should(?:n'?t|\s+not)\s+buy|"
    r"it'?s?\s+not\s+for))\s*[:\-–]?\s*([^\n.]{10,200})",
    re.IGNORECASE,
)


def _find_best_for(text: str) -> list[str]:
    return [m.group(1).strip().rstrip(".,") for m in _BEST_FOR_PAT.finditer(text)][:5]


def _find_not_for(text: str) -> list[str]:
    return [m.group(1).strip().rstrip(".,") for m in _NOT_FOR_PAT.finditer(text)][:5]


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------

def _extract(content: str) -> dict:
    return {
        "pros": _find_pros(content),
        "cons": _find_cons(content),
        "verdict": _find_verdict(content),
        "rating": _find_rating(content),
        "best_for": _find_best_for(content),
        "not_for": _find_not_for(content),
        "mentioned_price": _find_price(content),
    }
