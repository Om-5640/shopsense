"""
Analysis output normalizer.

The LLM analyzer returns a dict with materials/products/summary, but the exact
shape varies by which LLM produced it (Groq/Gemini/Mistral/Cerebras all have
quirks). This module coerces ANY shape into the canonical one we expect,
silently fixing or dropping malformed entries instead of crashing downstream.

Canonical shape:
{
    "summary": "string (always)",
    "materials": [
        {
            "name": "string",
            "mention_count": int,
            "distinct_recommenders": int,
            "praise": [str],
            "complaints": [{"text": str, "confidence": str}],
            "example_products": [str],
            "sources": [str],
        }
    ],
    "products": [
        {
            "name": "string",
            "mention_count": int,
            "distinct_recommenders": int,
            "positive_mentions": int,
            "negative_mentions": int,
            "praise": [str],
            "complaints": [{"text": str, "confidence": str}],
            "sources": [str],
            "signal_strength": "high|medium|low",
            "representative_quote": str,
            "cross_subreddit_signal": null,
        }
    ]
}
"""

import logging
import re

_logger = logging.getLogger(__name__)

try:
    from product_canonicalizer import canonicalize_product as _canonicalize_product
    _HAS_CANONICALIZER = True
except ImportError:
    _canonicalize_product = None  # type: ignore[assignment]
    _HAS_CANONICALIZER = False

# ── Array size caps — prevents unbounded growth from misbehaving LLMs ────────
MAX_PRAISE     = 20
MAX_COMPLAINTS = 20
MAX_SOURCES    = 50
MAX_PRODUCTS   = 50
MAX_MATERIALS  = 30


# ── Primitive coercers ────────────────────────────────────────────────────────

def _safe_str(value, default: str = "") -> str:
    """Coerce ANY value to a string. Dict→bulleted, list→joined, None→default."""
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        parts = []
        for k, v in value.items():
            label = str(k).replace("_", " ").title()
            v_str = _safe_str(v)
            if v_str:
                parts.append(f"{label}: {v_str}")
        return " | ".join(parts)
    if isinstance(value, list):
        return ", ".join(_safe_str(item) for item in value if item is not None)
    return str(value)


def _safe_int(value, default: int = 0) -> int:
    """Coerce to int. Strings like '5+' or 'many' become default."""
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+", value)
        if match:
            try:
                return int(match.group())
            except ValueError:
                pass
    return default


def _safe_count(value, default: int = 0) -> int:
    """Bug 3: count-specific helper — floors negative values to 0."""
    return max(0, _safe_int(value, default))


def _field_int(item: dict, primary: str, *fallbacks: str, default: int = 0) -> int:
    """
    Bug 1 & 2: explicit field precedence that handles falsy-zero values correctly.
    Uses 'in' membership check instead of 'or' so a value of 0 is never shadowed
    by a fallback field (e.g. mention_count=0 must not fall through to mentions=25).
    """
    for key in (primary, *fallbacks):
        if key in item:
            return _safe_count(item[key], default)
    return default


def _safe_list(value, item_coercer=None) -> list:
    """Coerce to list. Single value becomes [value]. None becomes []."""
    if value is None:
        return []
    if isinstance(value, list):
        result = value
    elif isinstance(value, (str, dict)):
        result = [value]
    else:
        result = []

    if item_coercer:
        return [item_coercer(item) for item in result if item is not None]
    return result


def _flatten_list(items: list) -> list:
    """
    Bug 4: recursively flatten nested lists so [[a, b], c] → [a, b, c].
    Non-list items pass through unchanged so normal entries are unaffected.
    """
    result = []
    for item in items:
        if isinstance(item, list):
            result.extend(_flatten_list(item))
        else:
            result.append(item)
    return result


# ── Complaint normalization ───────────────────────────────────────────────────

def _normalize_complaint(item) -> dict | None:
    """Complaints can come as strings or dicts. Always return dict with text+confidence."""
    if item is None:
        return None
    if isinstance(item, str):
        if not item.strip():
            return None
        return {"text": item.strip(), "confidence": "single"}
    if isinstance(item, dict):
        text = _safe_str(item.get("text") or item.get("complaint") or item.get("issue"))
        if not text:
            return None
        confidence = _safe_str(item.get("confidence", "single")).lower()
        if confidence not in {"confirmed", "reported", "single"}:
            confidence = "single"
        return {"text": text, "confidence": confidence}
    return None


# ── Deduplication ─────────────────────────────────────────────────────────────

def _canonical_key(name: str) -> str:
    """
    Primary dedup key: strip all punctuation/spaces, lowercase.
    "Sony WF-1000XM5", "Sony WF1000XM5", "SONY WF-1000XM5" → "sonywf1000xm5"
    """
    return re.sub(r"[\W_]", "", name.lower())


def _token_set_key(name: str) -> str:
    """
    Secondary dedup key: sorted unique word tokens, joined.
    Catches word-order variants: "Realme Buds Air 7" = "Realme Air Buds 7"
    → sorted tokens: ["7","air","buds","realme"] → "7|air|buds|realme"
    Returns "" for single-token names (avoids false matches).
    """
    tokens = sorted(set(re.findall(r'[a-z0-9]+', name.lower())))
    return "|".join(tokens) if len(tokens) >= 2 else ""


_SIG_RANK = {"high": 2, "medium": 1, "low": 0}


def _merge_products(base: dict, dup: dict) -> dict:
    """Accumulate counts and lists from a duplicate entry into base."""
    base["mention_count"]        = base.get("mention_count", 0)        + dup.get("mention_count", 0)
    base["positive_mentions"]    = base.get("positive_mentions", 0)    + dup.get("positive_mentions", 0)
    base["negative_mentions"]    = base.get("negative_mentions", 0)    + dup.get("negative_mentions", 0)
    base["distinct_recommenders"] = max(
        base.get("distinct_recommenders", 0),
        dup.get("distinct_recommenders", 0),
    )

    seen_praise = set(base["praise"])
    for p in dup.get("praise", []):
        if p not in seen_praise:
            base["praise"].append(p)
            seen_praise.add(p)

    seen_complaints = {c["text"] for c in base["complaints"]}
    for c in dup.get("complaints", []):
        if c["text"] not in seen_complaints:
            base["complaints"].append(c)
            seen_complaints.add(c["text"])

    seen_sources = set(base["sources"])
    for s in dup.get("sources", []):
        if s not in seen_sources:
            base["sources"].append(s)
            seen_sources.add(s)

    # Prefer higher signal_strength
    if _SIG_RANK.get(dup.get("signal_strength", "low"), 0) > _SIG_RANK.get(base.get("signal_strength", "low"), 0):
        base["signal_strength"] = dup["signal_strength"]

    # Keep the better representative_quote
    if not base.get("representative_quote") and dup.get("representative_quote"):
        base["representative_quote"] = dup["representative_quote"]

    # Enforce caps after merge
    base["praise"]      = base["praise"][:MAX_PRAISE]
    base["complaints"]  = base["complaints"][:MAX_COMPLAINTS]
    base["sources"]     = base["sources"][:MAX_SOURCES]
    return base


def _dedup_products(products: list[dict]) -> list[dict]:
    """
    Deduplicate products using two complementary keys:
    1. Primary (exact): strips all punctuation — handles "WF-1000XM5" == "WF1000XM5"
    2. Token-set: sorted word tokens — handles "Buds Air 7" == "Air Buds 7"
    First occurrence wins; duplicates are merged so counts accumulate.
    """
    seen_exact: dict[str, int] = {}   # canonical_key → index
    seen_tokens: dict[str, int] = {}  # token_set_key → index
    result: list[dict] = []
    for p in products:
        name = p.get("name", "")
        exact = _canonical_key(name)
        tokens = _token_set_key(name)

        # 1. Exact key match
        if exact and exact in seen_exact:
            result[seen_exact[exact]] = _merge_products(result[seen_exact[exact]], p)
            continue

        # 2. Token-set match (word-order variant)
        if tokens and tokens in seen_tokens:
            idx = seen_tokens[tokens]
            result[idx] = _merge_products(result[idx], p)
            # Register exact key for faster future lookups
            if exact:
                seen_exact[exact] = idx
            continue

        # New product
        idx = len(result)
        result.append(p)
        if exact:
            seen_exact[exact] = idx
        if tokens:
            seen_tokens[tokens] = idx
    return result


# ── Canonical product schema ──────────────────────────────────────────────────

def _build_product_template(name: str) -> dict:
    """
    Bug 7: single source of truth for the product schema.
    Used by both the main normalizer and the recovery path so downstream code
    always receives the same shape regardless of how the product was sourced.
    """
    return {
        "name":                  name,
        "mention_count":         0,
        "distinct_recommenders": 0,
        "positive_mentions":     0,
        "negative_mentions":     0,
        "praise":                [],
        "complaints":            [],
        "sources":               [],
        "signal_strength":       "low",
        "representative_quote":  "",
        "cross_subreddit_signal": None,
    }


# ── Per-item normalization ────────────────────────────────────────────────────

def _normalize_item(item, is_product: bool = False) -> dict | None:
    """
    Normalize a material or product entry to canonical shape.
    Returns None if entry is unusable (no name).
    """
    # LLM returned a bare string — wrap it using the template
    if isinstance(item, str):
        name = item.strip()
        if not name:
            return None
        if is_product:
            return _build_product_template(name)
        return {
            "name":                  name,
            "mention_count":         0,
            "distinct_recommenders": 0,
            "praise":                [],
            "complaints":            [],
            "example_products":      [],
            "sources":               [],
        }

    if not isinstance(item, dict):
        return None

    # Extract name from any of several possible keys (LLMs use different conventions)
    name = _safe_str(
        item.get("name") or item.get("product") or item.get("product_name") or
        item.get("material") or item.get("title") or item.get("category") or
        item.get("model") or item.get("item") or item.get("brand_model")
    )
    if not name:
        return None

    # Bug 4: flatten nested complaint lists before processing
    raw_complaints = _flatten_list(_safe_list(item.get("complaints")))

    normalized = {
        "name": name,
        # Bug 1 & 3: explicit field precedence + floor at 0
        "mention_count":         _field_int(item, "mention_count", "mentions"),
        # Bug 2 & 3: same for recommenders
        "distinct_recommenders": _field_int(item, "distinct_recommenders", "recommenders"),
        # Bug 8: cap array lengths
        "praise": [
            _safe_str(p) for p in _safe_list(item.get("praise")) if _safe_str(p)
        ][:MAX_PRAISE],
        "complaints": [
            c for c in (_normalize_complaint(x) for x in raw_complaints)
            if c is not None
        ][:MAX_COMPLAINTS],
        "sources": [
            _safe_str(s) for s in _safe_list(item.get("sources")) if _safe_str(s)
        ][:MAX_SOURCES],
    }

    if is_product:
        signal = _safe_str(item.get("signal_strength", "low")).lower()
        if signal not in {"high", "medium", "low"}:
            signal = "low"
        normalized["signal_strength"]        = signal
        normalized["cross_subreddit_signal"] = item.get("cross_subreddit_signal", None)
        # Bug 7: always present, never missing from product schema
        normalized["positive_mentions"]    = _safe_count(item.get("positive_mentions"), 0)
        normalized["negative_mentions"]    = _safe_count(item.get("negative_mentions"), 0)
        normalized["representative_quote"] = _safe_str(item.get("representative_quote", ""))
    else:
        normalized["example_products"] = [
            _safe_str(ex) for ex in _safe_list(item.get("example_products")) if _safe_str(ex)
        ]

    return normalized


# ── Top-level entry point ─────────────────────────────────────────────────────

def normalize_analysis(raw: dict | None) -> dict:
    """
    Take ANY LLM output and return a guaranteed-clean canonical dict.
    Never raises. Always returns a usable structure even if input is empty/garbage.
    """
    if not isinstance(raw, dict):
        return {"summary": _safe_str(raw), "materials": [], "products": []}

    summary = _safe_str(raw.get("summary", ""))

    materials = []
    for item in _safe_list(raw.get("materials")):
        norm = _normalize_item(item, is_product=False)
        if norm:
            materials.append(norm)

    products = []
    for item in _safe_list(raw.get("products")):
        norm = _normalize_item(item, is_product=True)
        if norm:
            products.append(norm)

    # ---- LAST-RESORT RECOVERY ----
    # If products is empty but summary clearly mentions product names,
    # extract them as a fallback so the user gets SOMETHING usable.
    if not products and summary:
        rescued = _extract_products_from_summary(summary)
        if rescued:
            _logger.info(
                "[normalizer] structured products empty - rescued %d from summary text",
                len(rescued),
            )
            products = rescued

    # Bug 5 & 6: dedup AFTER recovery so recovered items pass through the same
    # pipeline as structured products — no separate duplicate can survive.
    products = _dedup_products(products)
    # Fix 10: cap list sizes — prevents memory explosion from pathological LLM output
    products  = products[:MAX_PRODUCTS]
    materials = materials[:MAX_MATERIALS]

    # Fix 17: source_coverage — count of distinct sources that mentioned this product.
    # Single-source products carry lower evidence authority than multi-source ones.
    for p in products:
        p["source_coverage"] = len(set(p.get("sources") or []))

    return {"summary": summary, "materials": materials, "products": products}


# ── Last-resort recovery ──────────────────────────────────────────────────────

# Fix 7: module-level constant — sole fallback when canonicalize_product cannot
# find a recognised brand (requires 2+ consecutive digits to avoid "Gen 3", etc.)
_RE_MODEL_NUMBER = re.compile(r"\d{2,}")


def _strip_leading_words(candidate: str) -> str:
    """
    Fix 9: strip leading non-product words (verbs, adjectives) without a
    hardcoded word list.  Iteratively drops the first word while the canonical
    name from canonicalize_product does NOT start with it — meaning it is noise
    rather than part of the product identity.
    Stops when fewer than 3 words remain to guarantee a usable name.
    """
    if not _HAS_CANONICALIZER:
        return candidate
    words = candidate.split()
    while len(words) >= 3:
        cp = _canonicalize_product(" ".join(words))
        canon = cp.canonical_name
        if not canon or canon.lower().startswith(words[0].lower()):
            break
        words = words[1:]
    return " ".join(words)


def _extract_products_from_summary(summary: str) -> list[dict]:
    """
    Last-resort: when the LLM returned an empty products array but the summary
    text clearly mentions specific product names, extract them.

    Fix 7: brand detection delegates to product_canonicalizer — no hardcoded
    KNOWN_BRANDS set is maintained here.
    Fix 8: skip_phrases list removed — the brand/model-number structural filter
    already rejects generic heading-style phrases (no brand, no model digits).
    Fix 9: leading_verbs list removed — _strip_leading_words() dynamically
    strips non-product prefixes via canonical name comparison.
    Fix 10: result capped at MAX_PRODUCTS instead of a magic literal.
    """
    found: dict[str, int] = {}

    pattern = re.compile(
        r"\b([A-Z][a-zA-Z0-9]+(?:[\s-][A-Z0-9][a-zA-Z0-9]*){1,4})\b"
    )
    for match in pattern.finditer(summary):
        candidate = match.group(1).strip()
        if len(candidate.split()) < 2:
            continue

        # Fix 7: delegate brand detection to product_canonicalizer — no inline brand list
        has_known_brand = (
            _HAS_CANONICALIZER and _canonicalize_product(candidate).brand is not None
        )
        # Fallback: 2+ consecutive digits signal a genuine product model number
        has_model_number = bool(_RE_MODEL_NUMBER.search(candidate))

        if not has_known_brand and not has_model_number:
            continue

        found[candidate] = found.get(candidate, 0) + 1

    rescued: list[dict] = []
    for name, count in sorted(found.items(), key=lambda x: -x[1]):
        # Fix 9: strip leading noise words without a hardcoded verb list
        name = _strip_leading_words(name)
        if len(name.split()) < 2:
            continue

        entry = _build_product_template(name)
        entry["mention_count"] = count
        entry["_recovered_from_summary"] = True
        rescued.append(entry)

    return rescued[:MAX_PRODUCTS]
