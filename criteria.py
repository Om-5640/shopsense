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


SYSTEM = """You are a product research expert generating evaluation criteria for a specific product type.

These criteria will drive an interview (questions target uncovered criteria) and score products from reviews.

Return ONLY a JSON object:
{
  "criteria": [
    {
      "name": "snake_case_id",
      "label": "Human Readable Label",
      "description": "One sentence: what this measures",
      "high_score_means": "What a 10/10 product looks like on this criterion",
      "low_score_means": "What a 1/10 product looks like on this criterion"
    }
  ]
}

RULES:
1. Return 6–10 criteria. Only include what actually differentiates products in this EXACT category.
2. BE PRODUCT-SPECIFIC — use criterion names that only make sense for this product type:
   - "electronics/gaming-mouse" → sensor_tracking_accuracy, ergonomics_grip_fit, click_latency, polling_rate, weight_and_balance, switch_durability, wireless_performance, programmable_buttons
   - "electronics/earbuds" → sound_signature, anc_effectiveness, battery_life, call_quality, fit_and_stability, connection_stability, latency_for_video
   - "electronics/laptop" → cpu_performance, display_quality, battery_endurance, thermal_management, port_selection, keyboard_feel, build_durability
   - "skincare/sunscreen" → spf_protection_reliability, finish_texture, white_cast_level, skin_type_compatibility, water_resistance, ingredient_safety
   - "electronics/keyboard" → switch_feel_and_sound, layout_and_size, wireless_and_connectivity, software_and_customisation, typing_comfort, hot_swap_and_modability
3. FORBIDDEN generic criterion names (apply to every product, tell buyers nothing specific): "build_quality", "value_for_money", "fit_for_purpose", "user_satisfaction", "overall_quality", "durability" alone, "performance" alone. Use SPECIFIC names instead (e.g. "sensor_tracking_accuracy" not "performance").
4. ALWAYS include "price_to_value" — the one universal criterion that measures whether the product's performance justifies its price tier. This is the only exception to rule 3.
5. Include 1 "hidden expert criterion" — something casual buyers overlook but that expert reviews always test (e.g. gaming mouse → "debounce_consistency"; earbuds → "codec_support"; mattress → "edge_support"; sunscreen → "photostability").

JSON only. No markdown, no commentary."""


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
    """Emergency fallback when LLM generation fails entirely."""
    return [
        {"name": "core_performance", "label": "Core Performance",
         "description": "How well the product does its primary job",
         "high_score_means": "Excels at its main function",
         "low_score_means": "Fails at its main function"},
        {"name": "reliability", "label": "Reliability",
         "description": "Consistency and absence of defects over time",
         "high_score_means": "Zero reported failures, consistent results",
         "low_score_means": "Frequent failures, inconsistent performance"},
        {"name": "ergonomics_and_usability", "label": "Ergonomics & Ease of Use",
         "description": "How comfortable and intuitive it is to use",
         "high_score_means": "Effortless to use, well-designed",
         "low_score_means": "Uncomfortable or confusing to use"},
        {"name": "price_to_value", "label": "Price-to-Value Ratio",
         "description": "Whether the performance justifies the price tier",
         "high_score_means": "Punches above its price class",
         "low_score_means": "Overpriced relative to what you get"},
        {"name": "user_reported_satisfaction", "label": "Owner Satisfaction",
         "description": "What verified buyers say after extended use",
         "high_score_means": "Owners overwhelmingly recommend it",
         "low_score_means": "Common regret, frequent complaints"},
    ]