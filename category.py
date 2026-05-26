"""
Category detection.

Maps a user query to a stable category key. When the query is ambiguous
(e.g. "best watch" could be analog/smartwatch/fitness-tracker), returns a
disambiguation prompt with options for the user to pick from.

Choice is cached per query so repeat runs skip the prompt.
"""

import json
import re
import cache
from agents import run_agent


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


def detect_category(query: str) -> dict:
    """
    Returns {category, confidence, needs_disambiguation, options}.
    Cached so repeat queries are free.
    """
    cache_key = query.lower().strip()
    cached = cache.get("category", cache_key)
    if cached is not None:
        return cached

    prompt = f'Query: "{query}"\n\nClassify this with disambiguation if needed.'
    try:
        raw = run_agent("category_detector", user_prompt=prompt, system=SYSTEM)
        from llm_client import safe_json_loads
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
            # Disambiguation requested but options are bad - treat as unambiguous
            result["needs_disambiguation"] = False
            result["options"] = []
        else:
            result["options"] = clean_options[:5]  # cap at 5

    cache.set("category", cache_key, result)
    return result


def _sanitize_slug(slug: str) -> str:
    """Normalize a category slug: lowercase, only safe chars."""
    return re.sub(r"[^a-z0-9/\-]", "", slug.lower())


def _fallback_result() -> dict:
    return {
        "category": "general/item",
        "primary_noun": "item",
        "confidence": "low",
        "needs_disambiguation": False,
        "options": [],
    }


def category_to_filename(category: str) -> str:
    """Turn 'bedding/blanket' into 'bedding_blanket' for file paths."""
    return category.replace("/", "_")


def resolve_category_interactively(query: str, forced_category: str | None = None) -> dict:
    """
    Top-level entry. Returns final category info dict.

    If forced_category provided (via --category flag), uses that directly.
    Otherwise calls detect_category and prompts user to pick if disambiguation needed.
    """
    if forced_category:
        return {
            "category": _sanitize_slug(forced_category),
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
    print(f"  Your query could mean different things. Which type did you mean?")
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
            "confidence": "high",
            "needs_disambiguation": False,
            "options": [],
        }
        # Cache the user's choice so they don't get re-asked for same query
        cache.set("category", query.lower().strip(), result)
        print(f"[category] using: {chosen['slug']}")
        return result
    else:
        # User chose "none of these" - keep generic
        result = {
            "category": detection["category"],
            "confidence": "low",
            "needs_disambiguation": False,
            "options": [],
        }
        cache.set("category", query.lower().strip(), result)
        print(f"[category] keeping generic: {result['category']}")
        return result