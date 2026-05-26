"""
Rubric.

Combines category criteria + user profile into a weighted scorecard.
Each criterion gets a weight 0-10 with a rationale tying it to the user's profile.

Stored at rubrics/<category>.json so it can be reused/edited.
"""

import json
from pathlib import Path
from datetime import datetime
from agents import run_agent
from category import category_to_filename


RUBRICS_DIR = Path(__file__).parent / "rubrics"
RUBRICS_DIR.mkdir(exist_ok=True)


# ---- storage ----

def rubric_path(category: str) -> Path:
    return RUBRICS_DIR / f"{category_to_filename(category)}.json"


def load_rubric(category: str) -> dict | None:
    path = rubric_path(category)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_rubric(category: str, rubric: dict) -> None:
    path = rubric_path(category)
    rubric["category"] = category
    rubric["last_updated"] = datetime.utcnow().isoformat() + "Z"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rubric, f, indent=2)


# ---- generation ----

GEN_SYSTEM = """You build personalized scoring rubrics for product purchases.

Given product criteria + the user's stated preferences, assign each criterion a weight 0-10 reflecting how important it is FOR THIS USER.

Return ONLY a JSON object:
{
  "weighted_criteria": [
    {
      "name": "snake_case_id",
      "label": "Human Label",
      "weight": 0-10,
      "rationale": "Why this weight, tied to user's preferences"
    }
  ]
}

RULES:
1. Use the EXACT criterion names provided. Don't invent new ones.
2. Weight reflects importance to THIS USER, not generic importance.
3. Tie every rationale to something specific the user said. Example: "user said runs hot → breathability critical → weight 9"
4. Default to 5 if user didn't address a criterion. Don't default everything to 5 though - infer when reasonable.
5. If user said "low priority" for something explicitly, weight it 1-3.
6. If user said it's a must-have, weight it 9-10.

NO markdown, NO commentary, JSON only."""


def generate_rubric(category: str, criteria: list[dict], profile: dict) -> dict:
    """Build a weighted rubric from criteria + profile."""
    criteria_text = "\n".join(
        f"- {c['name']}: {c['label']} ({c.get('description', '')})"
        for c in criteria
    )
    prefs = profile.get("preferences_summary", "")
    qa_text = "\n".join(
        f"Q: {qa['question']}\nA: {qa['answer']}"
        for qa in profile.get("interview", [])
    )

    prompt = f"""Category: {category}

Criteria to weight:
{criteria_text}

User's preferences summary:
{prefs}

Full interview Q&A:
{qa_text}

Build the weighted rubric."""

    raw = run_agent("rubric_generator", user_prompt=prompt, system=GEN_SYSTEM)
    try:
        from llm_client import _try_repair_json
        data = _try_repair_json(raw)
        weighted = data.get("weighted_criteria", [])
    except Exception:
        print("[rubric] JSON parse failed, using defaults")
        weighted = [_default_weight(c) for c in criteria]

    # Validate: every criterion must be present
    by_name = {w.get("name"): w for w in weighted if isinstance(w, dict)}
    final = []
    for c in criteria:
        w = by_name.get(c["name"])
        if w and isinstance(w.get("weight"), (int, float)):
            final.append({
                "name": c["name"],
                "label": c["label"],
                "weight": max(0, min(10, int(w["weight"]))),
                "rationale": w.get("rationale", ""),
                "description": c.get("description", ""),
            })
        else:
            final.append(_default_weight(c))

    rubric = {
        "weighted_criteria": final,
        "based_on_profile": profile.get("last_updated", ""),
    }
    save_rubric(category, rubric)
    return rubric


def _default_weight(criterion: dict) -> dict:
    return {
        "name": criterion["name"],
        "label": criterion["label"],
        "weight": 5,
        "rationale": "Default weight - not addressed in interview",
        "description": criterion.get("description", ""),
    }


# ---- criterion gap-filling ----

GAP_FILL_SYSTEM = """You assign reasonable default weights (0-10) for product criteria the user didn't explicitly address.

For each uncovered criterion, infer a weight based on:
1. Category norms — how important is this criterion typically for this product class? (e.g., refrigerant type matters more for AC than for blankets)
2. User's stated preferences — does anything they DID say imply something about this criterion? (e.g., "uses on solar panels" implies energy efficiency matters)
3. Research signal — if many products are praised/criticized on this criterion, it likely matters

Weight scale:
- 8-10: critical for this category (e.g., audio quality for headphones)
- 6-7: meaningfully important (e.g., warranty for big appliances)
- 4-5: nice to have, secondary
- 1-3: largely irrelevant for this category

Return ONLY a JSON object:
{
  "inferred_weights": [
    {
      "name": "snake_case_criterion_id",
      "weight": 0-10,
      "rationale": "Brief inference explanation citing category norms or user signal"
    }
  ]
}

Be HONEST with weights. Don't default everything to 5. If a criterion is genuinely important for this category, weight it 6-8 even without explicit user input.

NO markdown, NO commentary, JSON only."""


def fill_criterion_gaps(rubric: dict, category: str, profile: dict, research_summary: str = "") -> dict:
    """
    For criteria in the rubric that have default rationales ("not addressed in interview"),
    re-infer weights using category norms + research data instead of leaving them at 5.

    This eliminates the "all defaults are 5" problem when interview can't cover all criteria.
    """
    # Find criteria with default rationale
    defaulted = [
        c for c in rubric["weighted_criteria"]
        if "not addressed" in c.get("rationale", "").lower()
        or "Default weight" in c.get("rationale", "")
        or "neutral weight" in c.get("rationale", "").lower()
        or "neutral default" in c.get("rationale", "").lower()
    ]

    if not defaulted:
        return rubric  # nothing to fill

    print(f"[rubric] inferring weights for {len(defaulted)} unaddressed criteria...")

    # Build prompt
    defaulted_text = "\n".join(
        f"- {c['name']}: {c['label']} ({c.get('description', '')})"
        for c in defaulted
    )
    prefs = profile.get("preferences_summary", "")
    research_snippet = research_summary[:5000] if research_summary else "(no research yet)"

    prompt = f"""Category: {category}

User's stated preferences:
{prefs}

Criteria the user didn't directly address (assign weights to these):
{defaulted_text}

Research context (community discussion about this category):
{research_snippet}

For each uncovered criterion above, assign a weight 0-10 based on category importance + any indirect signal from the user's preferences."""

    try:
        raw = run_agent("gap_filler", user_prompt=prompt, system=GAP_FILL_SYSTEM)
        from llm_client import safe_json_loads
        data = safe_json_loads(raw)
        inferred = data.get("inferred_weights", []) if isinstance(data, dict) else []
    except Exception as e:
        print(f"[rubric] gap-fill failed ({e}), keeping defaults")
        return rubric

    # Apply inferred weights
    inferred_map = {w.get("name"): w for w in inferred if isinstance(w, dict)}
    updated_count = 0
    for c in rubric["weighted_criteria"]:
        _rat = c.get("rationale", "").lower()
        if c["name"] in inferred_map and (
            "not addressed" in _rat
            or "default weight" in _rat
            or "neutral" in _rat
        ):
            new_w = inferred_map[c["name"]]
            if isinstance(new_w.get("weight"), (int, float)):
                c["weight"] = max(0, min(10, int(new_w["weight"])))
                c["rationale"] = f"[inferred] {new_w.get('rationale', '')}"
                updated_count += 1

    if updated_count:
        print(f"[rubric] inferred weights applied to {updated_count} criteria")
        save_rubric(rubric.get("category", ""), rubric)
    return rubric


# ---- display ----

def display_rubric(rubric: dict) -> None:
    """Print the rubric in a readable format."""
    print(f"\n{'─'*72}")
    print("  YOUR PERSONALIZED RUBRIC")
    print(f"{'─'*72}\n")
    items = sorted(rubric["weighted_criteria"], key=lambda x: x["weight"], reverse=True)
    for i, c in enumerate(items, 1):
        bar = "█" * c["weight"] + "░" * (10 - c["weight"])
        print(f"{i:2}. {c['label']:30} [{bar}] {c['weight']}/10")
        if c.get("rationale"):
            print(f"    {c['rationale']}")
        print()


# ---- editing ----

def edit_weights(rubric: dict) -> dict:
    """Interactive weight editing. Returns the updated rubric."""
    print(f"\n{'─'*72}")
    print("  EDIT WEIGHTS")
    print(f"  Enter a new weight (0-10) or press Enter to keep current.")
    print(f"{'─'*72}\n")

    for c in rubric["weighted_criteria"]:
        print(f"{c['label']} (current: {c['weight']})")
        if c.get("rationale"):
            print(f"  rationale: {c['rationale']}")
        try:
            new_val = input(f"  new weight: ").strip()
        except (EOFError, KeyboardInterrupt):
            new_val = ""

        if new_val:
            try:
                v = int(new_val)
                if 0 <= v <= 10:
                    c["weight"] = v
                    c["rationale"] = (c.get("rationale", "") + " [manually adjusted]").strip()
                else:
                    print(f"  (kept {c['weight']} - value out of range)")
            except ValueError:
                print(f"  (kept {c['weight']} - not a number)")
        print()

    return rubric


# ---- checkpoint flow ----

def review_rubric(rubric: dict) -> dict:
    """
    Show rubric to user, allow edit, return final rubric.
    Used at both checkpoints (before research + after results).
    """
    display_rubric(rubric)
    try:
        choice = input("Approve rubric? (yes/edit) [yes]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        choice = "yes"

    if choice in {"edit", "e"}:
        rubric = edit_weights(rubric)
        # Re-save after edits
        save_rubric(rubric.get("category", ""), rubric)
    return rubric