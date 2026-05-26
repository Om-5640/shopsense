"""
Criteria generation.

For a category like "bedding/blanket", asks Gemini: "what should someone care
about when buying this?" Returns a structured list of criteria.

Cached per category so the second user researching blankets doesn't pay the
generation cost again.
"""

import cache
from agents import run_agent
from llm_client import safe_json_loads as _extract_json


SYSTEM = """You are a product research expert. Given a product category, list the things a meticulous buyer should evaluate before purchasing.

Return ONLY a JSON object with this shape:
{
  "criteria": [
    {
      "name": "snake_case_id",
      "label": "Human Readable Label",
      "description": "What this criterion measures",
      "high_score_means": "What a 10/10 looks like",
      "low_score_means": "What a 0/10 looks like"
    }
  ]
}

RULES:
1. 6-12 criteria. Don't be exhaustive, focus on what actually matters.
2. Cover the full decision: quality, fit-for-purpose, durability, price, brand trust, ergonomics, etc.
3. Be category-specific. For blankets: GSM, material, breathability, weight, washability, allergens, temperature regulation, durability, price, sizing. For keyboards: switch type, layout, build quality, key feel, software, price, etc.
4. Include 1-2 criteria most buyers forget but matter (e.g. "noise level" for keyboards, "off-gassing" for mattresses).
5. Snake_case names like "temperature_regulation", "switch_type", "build_quality".

NO markdown, NO commentary, JSON only."""


def generate_criteria(category: str) -> list[dict]:
    """
    Returns list of criterion dicts. Cached forever per category.
    """
    cached = cache.get("criteria", category)
    if cached is not None:
        print(f"[criteria] cache hit for {category}")
        return cached

    print(f"[criteria] generating for {category}...")
    prompt = f'Product category: "{category}"\n\nGenerate the buying criteria.'
    raw = run_agent("criteria_generator", user_prompt=prompt, system=SYSTEM)

    try:
        data = _extract_json(raw)
        criteria = data.get("criteria", [])
    except Exception as e:
        print(f"[criteria] JSON parse failed: {e}")
        return _fallback_criteria()

    # Validate
    if not isinstance(criteria, list) or len(criteria) < 4:
        print(f"[criteria] too few criteria ({len(criteria)}), using fallback")
        return _fallback_criteria()

    # Sanity check each one has required fields
    clean = []
    for c in criteria:
        if not isinstance(c, dict):
            continue
        if not c.get("name") or not c.get("label"):
            continue
        clean.append({
            "name": c["name"],
            "label": c["label"],
            "description": c.get("description", ""),
            "high_score_means": c.get("high_score_means", ""),
            "low_score_means": c.get("low_score_means", ""),
        })

    if len(clean) < 4:
        return _fallback_criteria()

    cache.set("criteria", category, clean)
    return clean


def _fallback_criteria() -> list[dict]:
    """Used if generation fails - generic but usable."""
    return [
        {"name": "quality", "label": "Build Quality", "description": "Materials and construction",
         "high_score_means": "Premium materials, excellent construction",
         "low_score_means": "Cheap materials, poor construction"},
        {"name": "value", "label": "Value for Money", "description": "Quality relative to price",
         "high_score_means": "Excellent value, punches above price",
         "low_score_means": "Overpriced for what you get"},
        {"name": "durability", "label": "Durability", "description": "Lifespan and longevity",
         "high_score_means": "Lasts years with regular use",
         "low_score_means": "Wears out quickly"},
        {"name": "fit_for_purpose", "label": "Fit For Purpose", "description": "Does the core job well",
         "high_score_means": "Excels at primary use case",
         "low_score_means": "Struggles at primary use case"},
        {"name": "user_satisfaction", "label": "User Satisfaction", "description": "Overall reported happiness",
         "high_score_means": "Users overwhelmingly satisfied",
         "low_score_means": "Common complaints, regret"},
    ]