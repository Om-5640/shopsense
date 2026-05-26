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
            "praise": [str],
            "complaints": [{"text": str, "confidence": str}],
            "sources": [str],
            "signal_strength": "high|medium|low",
        }
    ]
}
"""


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
        # Handle '5+', '~10', 'many', etc.
        import re
        match = re.search(r"-?\d+", value)
        if match:
            try:
                return int(match.group())
            except ValueError:
                pass
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


def _normalize_item(item, is_product: bool = False) -> dict | None:
    """
    Normalize a material or product entry to canonical shape.
    Returns None if entry is unusable (no name).
    """
    # If LLM returned a bare string (just a name), wrap it
    if isinstance(item, str):
        name = item.strip()
        if not name:
            return None
        return {
            "name": name,
            "mention_count": 0,
            "distinct_recommenders": 0,
            "praise": [],
            "complaints": [],
            "example_products": [] if not is_product else None,
            "sources": [],
            "signal_strength": "low" if is_product else None,
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

    normalized = {
        "name": name,
        "mention_count": _safe_int(item.get("mention_count") or item.get("mentions"), 0),
        "distinct_recommenders": _safe_int(
            item.get("distinct_recommenders") or item.get("recommenders"), 0
        ),
        "praise": [_safe_str(p) for p in _safe_list(item.get("praise")) if _safe_str(p)],
        "complaints": [
            c for c in (_normalize_complaint(x) for x in _safe_list(item.get("complaints")))
            if c is not None
        ],
        "sources": [_safe_str(s) for s in _safe_list(item.get("sources")) if _safe_str(s)],
    }

    if is_product:
        signal = _safe_str(item.get("signal_strength", "low")).lower()
        if signal not in {"high", "medium", "low"}:
            signal = "low"
        normalized["signal_strength"] = signal
        # v7: cross-subreddit signal (set to None until cross_validate.py runs)
        normalized["cross_subreddit_signal"] = item.get("cross_subreddit_signal", None)
        # Preserve fields requested in EXTRACT_PROMPT_TEMPLATE that were previously dropped
        normalized["positive_mentions"] = _safe_int(item.get("positive_mentions"), 0)
        normalized["negative_mentions"] = _safe_int(item.get("negative_mentions"), 0)
        normalized["representative_quote"] = _safe_str(item.get("representative_quote", ""))
    else:
        # Materials carry example products
        normalized["example_products"] = [
            _safe_str(ex) for ex in _safe_list(item.get("example_products")) if _safe_str(ex)
        ]

    return normalized


def normalize_analysis(raw: dict | None) -> dict:
    """
    Take ANY LLM output and return a guaranteed-clean canonical dict.
    Never raises. Always returns a usable structure even if input is empty/garbage.
    """
    if not isinstance(raw, dict):
        return {
            "summary": _safe_str(raw),
            "materials": [],
            "products": [],
        }

    # Normalize summary (handle dict-summaries from misbehaving LLMs)
    summary = _safe_str(raw.get("summary", ""))

    # Normalize materials
    raw_materials = _safe_list(raw.get("materials"))
    materials = []
    for item in raw_materials:
        norm = _normalize_item(item, is_product=False)
        if norm:
            materials.append(norm)

    # Normalize products
    raw_products = _safe_list(raw.get("products"))
    products = []
    for item in raw_products:
        norm = _normalize_item(item, is_product=True)
        if norm:
            products.append(norm)

    # ---- LAST-RESORT RECOVERY ----
    # If products is empty but summary clearly mentions product names,
    # extract them as a fallback so the user gets SOMETHING usable.
    if not products and summary:
        rescued = _extract_products_from_summary(summary)
        if rescued:
            print(f"[normalizer] structured products empty - rescued {len(rescued)} from summary text")
            products = rescued

    return {
        "summary": summary,
        "materials": materials,
        "products": products,
    }


def _extract_products_from_summary(summary: str) -> list[dict]:
    """
    Last-resort: when the LLM returned an empty products array but the summary
    text clearly mentions specific product names, extract them.

    Looks for patterns like:
    - "Realme Buds Air 7"  (Brand + ProductName + Number)
    - "OnePlus Nord Buds 3 Pro"
    - "CMF Buds Pro"
    - "Sony WF-1000XM5"

    Only returns confident matches: 2+ capitalized words OR a known brand pattern.
    """
    import re

    # Known consumer-electronics brand patterns we want to surface
    KNOWN_BRANDS = {
        # Earbuds / audio
        "Sony", "Bose", "Sennheiser", "Apple", "AirPods", "Samsung", "Galaxy",
        "JBL", "Skullcandy", "Anker", "Soundcore", "Jabra", "Beats", "Beyerdynamic",
        "Audio-Technica", "Shure", "Moondrop", "1More", "Edifier",
        "Realme", "OnePlus", "Oppo", "Xiaomi", "Redmi", "Mi", "Nothing",
        "Boat", "Boult", "Noise", "PTron", "PTRON", "Truke", "Mivi", "CMF",
        # Watches
        "Casio", "Titan", "Timex", "Fossil", "Rolex", "Omega", "Seiko", "Citizen",
        "Tissot", "Hamilton", "Tag Heuer", "Tudor", "Grand Seiko", "Longines",
        "HMT", "Fastrack",
        # Phones
        "Pixel", "iPhone", "Motorola", "Nokia",
        # Appliances
        "Daikin", "LG", "Voltas", "Hitachi", "Lloyd", "Blue Star", "Mitsubishi",
        "Panasonic", "Carrier", "Midea", "Frigidaire", "Whynter",
        # General electronics
        "Dell", "HP", "Asus", "Lenovo", "Acer", "MSI", "Logitech", "Razer",
    }

    found = {}  # name → mention_count

    # Pattern 1: Multi-word capitalized product names (Brand + Model)
    # Matches: "Realme Buds Air 7", "OnePlus Nord Buds 3 Pro", "Sony WF-1000XM5"
    pattern = re.compile(
        r"\b([A-Z][a-zA-Z0-9]+(?:[\s-][A-Z0-9][a-zA-Z0-9]*){1,4})\b"
    )
    for match in pattern.finditer(summary):
        candidate = match.group(1).strip()
        # Skip if it's a single word or just numbers
        words = candidate.split()
        if len(words) < 2:
            continue
        # Skip if no known brand AND no digit (model number)
        has_known_brand = any(w in KNOWN_BRANDS or w.split("-")[0] in KNOWN_BRANDS for w in words)
        has_digit = any(c.isdigit() for c in candidate)
        if not has_known_brand and not has_digit:
            continue
        # Skip common non-product capitalized phrases
        skip_phrases = {"Top Picks", "Budget Buys", "Red Flags", "Final Advice",
                        "Best Overall", "Best Budget", "Budget Opportunity",
                        "Under Rs", "Hi-Res Audio", "Reddit India"}
        if any(s in candidate for s in skip_phrases):
            continue

        found[candidate] = found.get(candidate, 0) + 1

    # Build canonical product dicts from the matches
    # Strip leading verb words like "Avoid X" -> "X"
    leading_verbs = {"Avoid", "Skip", "Get", "Buy", "Try", "Use", "Choose", "Pick", "Consider"}
    rescued = []
    for name, count in sorted(found.items(), key=lambda x: -x[1]):
        words = name.split()
        if words and words[0] in leading_verbs:
            cleaned = " ".join(words[1:])
            if len(cleaned.split()) >= 2:  # still has at least 2 words
                name = cleaned
            else:
                continue  # was just "Avoid X", not useful
        rescued.append({
            "name": name,
            "mention_count": count,
            "distinct_recommenders": 0,
            "praise": [],
            "complaints": [],
            "sources": [],
            "signal_strength": "low",
            "_recovered_from_summary": True,
        })

    return rescued[:15]


# ----- old normalize entry point kept above. recovery now happens inside it -----