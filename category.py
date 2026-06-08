"""
Category detection.

Maps a user query to a stable category key. When the query is ambiguous
(e.g. "best watch" could be analog/smartwatch/fitness-tracker), returns a
disambiguation prompt with options for the user to pick from.

Choice is cached per query so repeat runs skip the prompt.
"""

import re
from functools import lru_cache

import cache
from agents import run_agent
from llm_client import safe_json_loads


SYSTEM = """You classify shopping queries into product categories.

Return ONLY a JSON object with this exact shape:
{
  "category": "domain/item",
  "primary_noun": "exact product the user wants to buy (e.g. facewash, earbuds, mattress)",
  "confidence": "high|medium|low",
  "needs_disambiguation": true|false,
  "options": [
    {"slug": "domain/specific", "label": "Human readable explanation of what this is"},
    ...
  ]
}

PRIMARY NOUN RULE:
Extract the EXACT product type the user intends to BUY. Ignore use-cases and goals.
- "best facewash for tan removal" → primary_noun = "facewash" (NOT "tan removal product")
- "best earbuds under ₹3000" → primary_noun = "earbuds"
- "best laptop for video editing" → primary_noun = "laptop"
- "best sunscreen for oily skin" → primary_noun = "sunscreen"
The primary_noun MUST be the actual physical product, not the benefit or use-case.

CATEGORY SLUG FORMAT:
- Lowercase, hyphens for spaces, slashes for hierarchy
- Examples: "bedding/blanket", "electronics/earbuds", "watches/analog"

DISAMBIGUATION RULES:
Set needs_disambiguation=true when a single query word could mean multiple distinct product types.

CLEAR AMBIGUOUS CASES (always disambiguate):
- "watch" → analog, smartwatch, fitness-tracker
- "headphones" → wired, wireless over-ear, in-ear earbuds, gaming
- "monitor" → general computing, gaming, professional/color-accurate
- "speaker" → bluetooth portable, smart speaker, bookshelf/hi-fi
- "knife" → kitchen, EDC/pocket, tactical, hunting
- "bag" → backpack, messenger, travel, laptop sleeve
- "shoes" → running, hiking, casual, formal, basketball
- "camera" → DSLR, mirrorless, action, point-and-shoot, phone-attachment
- "router" → wifi home, business, mesh, travel
- "chair" → office/ergonomic, gaming, dining, accent/lounge
- "keyboard" → mechanical gaming, ergonomic office, wireless productivity
- "mouse" → gaming, productivity/ergonomic
- "blender" → personal, countertop, immersion, commercial
- "bike" → road, mountain, hybrid, electric, kids
- "lens" → camera lens type, contact lens, eyeglass

CLEAR UNAMBIGUOUS CASES (don't disambiguate):
- "best blanket for hot sleepers" → bedding/blanket (specific use case given)
- "best running shoes for flat feet" → footwear/running-shoes (specific given)
- "best mechanical keyboard" → electronics/keyboard-mechanical (specific given)

When user query has 1-2 generic words AND the noun is in the ambiguous list above, ALWAYS disambiguate.

When disambiguating:
- Provide 2-4 options
- Each option's label should briefly explain what falls in that category with example brand names if helpful
- Set "category" to the most likely option as a tentative default
- Set confidence to "low" when disambiguating

When NOT disambiguating:
- Set needs_disambiguation=false
- Provide empty options array []
- Set confidence to "high" or "medium"

NO markdown, NO commentary, JSON only."""


# ─── Public API ───────────────────────────────────────────────────────────────

def detect_category(query: str) -> dict:
    """
    Returns a *copy* of {category, primary_noun, confidence, needs_disambiguation, options}.

    Always returns a fresh copy so callers can safely add keys (e.g. region)
    without corrupting the shared LRU cache entry (Bug 1 + Bug 2 fix).

    Normalises the query before the LRU lookup so "Keyboard" and "keyboard"
    resolve to the same cached entry (Bug 3 fix).
    """
    return dict(_detect_category_cached(query.lower().strip()))


# ─── LRU-cached inner function (keyed on normalised query) ────────────────────

@lru_cache(maxsize=256)
def _detect_category_cached(norm_query: str) -> dict:
    """
    All actual detection logic lives here. The LRU key is the already-normalised
    query, so case/whitespace variants share the same slot.
    """
    rule_based = _rule_based_result(norm_query)
    if rule_based is not None:
        # Rule-based results are deterministic — no need to persist to disk (Bug 5 fix).
        return rule_based

    cached = cache.get("category", norm_query)
    if cached is not None:
        return cached

    prompt = f'Query: "{norm_query}"\n\nClassify this with disambiguation if needed.'
    try:
        raw = run_agent("category_detector", user_prompt=prompt, system=SYSTEM)
        data = safe_json_loads(raw)
    except Exception as e:
        print(f"[category] detection failed ({e}), using fallback")
        return _fallback_result()

    # Validate shape
    if not isinstance(data.get("category"), str) or "/" not in data.get("category", ""):
        return _fallback_result()

    # Extract primary_noun; fall back to last slug segment
    raw_noun = data.get("primary_noun", "")
    if not raw_noun or not isinstance(raw_noun, str):
        raw_noun = data.get("category", "general/item").split("/")[-1].replace("-", " ")
    primary_noun = raw_noun.strip().lower()

    result = {
        "category": _sanitize_slug(data["category"]),
        "primary_noun": primary_noun,
        "confidence": data.get("confidence", "medium"),
        "needs_disambiguation": bool(data.get("needs_disambiguation", False)),
        "options": [],
    }

    if result["confidence"] not in {"high", "medium", "low"}:
        result["confidence"] = "medium"

    # Validate options if disambiguation requested
    if result["needs_disambiguation"]:
        raw_options = data.get("options", [])
        clean_options = []
        if isinstance(raw_options, list):
            for opt in raw_options:
                if not isinstance(opt, dict):
                    continue
                slug = opt.get("slug", "")
                label = opt.get("label", "")
                if slug and label and "/" in slug:
                    clean_options.append({
                        "slug": _sanitize_slug(slug),
                        "label": label[:200],
                    })

        if len(clean_options) < 2:
            # Disambiguation requested but options are bad — treat as unambiguous
            result["needs_disambiguation"] = False
            result["options"] = []
        else:
            result["options"] = clean_options[:4]  # system prompt says 2-4 (Bug 6 fix)

    # Fix 16: surface low-confidence categories so frontend can prompt user before
    # the interview starts, not during it. Confidence "low" means the system couldn't
    # reliably determine the product type — a wrong category wastes the whole interview.
    result["needs_clarification"] = result["needs_disambiguation"] or result["confidence"] == "low"

    cache.set("category", norm_query, result)
    return result


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _sanitize_slug(slug: str) -> str:
    """Normalize a category slug: lowercase, only safe chars."""
    return re.sub(r"[^a-z0-9/\-]", "", slug.lower())


def _fallback_result() -> dict:
    return {
        "category": "general/item",
        "primary_noun": "item",
        "confidence": "low",
        "needs_disambiguation": False,
        "needs_clarification": True,   # Fix 16: low confidence → always clarify
        "options": [],
    }


def _rule_based_result(query: str) -> dict | None:
    """High-confidence fixes for common product nouns that must not drift."""
    if re.search(r"\bkeyboard(s)?\b", query):
        if re.search(r"\bmechanical\b|\bhot[-\s]?swappable\b|\bswitch(?:es)?\b", query):
            return {
                "category": "electronics/keyboard-mechanical",
                "primary_noun": "mechanical keyboard",
                "confidence": "high",
                "needs_disambiguation": False,
                "needs_clarification": False,
                "options": [],
            }

        return {
            "category": "electronics/keyboard",
            "primary_noun": "keyboard",
            "confidence": "medium",
            "needs_disambiguation": True,
            "needs_clarification": True,   # Fix 16
            "options": [
                {
                    "slug": "electronics/keyboard-mechanical",
                    "label": "Mechanical keyboard for typing, coding, or gaming",
                },
                {
                    "slug": "electronics/keyboard-wireless",
                    "label": "Wireless productivity keyboard for office or multi-device use",
                },
                {
                    "slug": "electronics/keyboard-ergonomic",
                    "label": "Ergonomic keyboard for comfort and wrist posture",
                },
            ],
        }

    return None


# ─── Validation & path utilities ──────────────────────────────────────────────

def validate_category_slug(category: str) -> str:
    """
    Sanitise a category string before it is used in any file-system path.
    Strips all characters not in [a-z0-9/_-] and raises ValueError if the
    result is empty or the input looks like a path-traversal attempt.
    """
    if not category or not isinstance(category, str):
        raise ValueError("category must be a non-empty string")
    clean = _sanitize_slug(category)
    if not clean:
        raise ValueError(f"category slug became empty after sanitisation: {category!r}")
    if ".." in clean or clean.startswith("/"):
        raise ValueError(f"category slug failed path-traversal check: {clean!r}")
    return clean


def category_to_filename(category: str) -> str:
    """Turn 'bedding/blanket' into 'bedding_blanket' for file paths."""
    safe = validate_category_slug(category)
    return safe.replace("/", "_")


# ─── CLI entry point ──────────────────────────────────────────────────────────

def resolve_category_interactively(query: str, forced_category: str | None = None) -> dict:
    """
    Top-level entry. Returns final category info dict.

    If forced_category provided (via --category flag), uses that directly.
    Otherwise calls detect_category and prompts user to pick if disambiguation needed.
    """
    if forced_category:
        # Bug 4 fix: include primary_noun so callers don't get KeyError
        slug = _sanitize_slug(forced_category)
        return {
            "category": slug,
            "primary_noun": slug.split("/")[-1].replace("-", " "),
            "confidence": "high",
            "needs_disambiguation": False,
            "options": [],
        }

    detection = detect_category(query)

    if not detection["needs_disambiguation"]:
        return detection

    # Prompt user to choose
    print(f"\n{'─'*72}")
    print("  CATEGORY CHECK")
    print("  Your query could mean different things. Which type did you mean?")
    print(f"{'─'*72}")

    options = detection["options"]
    for i, opt in enumerate(options, 1):
        print(f"    {i}. {opt['label']}")
        print(f"       category: {opt['slug']}")

    skip_index = len(options) + 1
    print(f"    {skip_index}. None of these / keep generic")

    default_choice = "1"
    try:
        choice = input(f"Choose (1-{skip_index}) [default {default_choice}]: ").strip() or default_choice
    except (EOFError, KeyboardInterrupt):
        choice = default_choice

    try:
        idx = int(choice) - 1
    except ValueError:
        idx = 0

    if 0 <= idx < len(options):
        chosen = options[idx]
        result = {
            "category": chosen["slug"],
            "primary_noun": chosen["slug"].split("/")[-1].replace("-", " "),
            "confidence": "high",
            "needs_disambiguation": False,
            "options": [],
        }
        cache.set("category", query.lower().strip(), result)
        print(f"[category] using: {chosen['slug']}")
        return result
    else:
        result = {
            "category": detection["category"],
            "primary_noun": detection.get("primary_noun", detection["category"].split("/")[-1].replace("-", " ")),
            "confidence": "low",
            "needs_disambiguation": False,
            "options": [],
        }
        cache.set("category", query.lower().strip(), result)
        print(f"[category] keeping generic: {result['category']}")
        return result
