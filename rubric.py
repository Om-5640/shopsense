"""
Rubric.

Combines category criteria + user profile into a weighted scorecard.
Each criterion gets a weight 0-10 with a rationale tying it to the user's profile.

Stored at rubrics/<category>.json so it can be reused/edited.
"""

import json
import logging
import re
import threading
from pathlib import Path
from datetime import datetime
from agents import run_agent
from category import category_to_filename

_logger = logging.getLogger(__name__)


RUBRICS_DIR = Path(__file__).parent / "rubrics"
RUBRICS_DIR.mkdir(exist_ok=True)

# Per-category file locks — prevents concurrent same-category searches from
# corrupting rubrics/<category>.json via interleaved writes.
_rubric_file_locks: dict[str, threading.Lock] = {}
_rubric_locks_mutex = threading.Lock()


def _get_rubric_lock(category: str) -> threading.Lock:
    with _rubric_locks_mutex:
        if category not in _rubric_file_locks:
            _rubric_file_locks[category] = threading.Lock()
        return _rubric_file_locks[category]


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
    with _get_rubric_lock(category):
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


def _build_intent_context(profile: dict) -> str:
    """
    Extract a compact hard-constraints block from profile intent.
    Returns empty string if no intent or no constraints.
    Used to make hard requirements explicit in rubric/scorer prompts.
    """
    intent = profile.get("intent") if isinstance(profile, dict) else None
    if not intent or not isinstance(intent, dict):
        return ""
    parts = []
    if intent.get("hard_constraints"):
        parts.append("HARD REQUIREMENTS (user said MUST/NEVER/required/allergic):")
        for c in intent["hard_constraints"][:6]:
            parts.append(f"  ⚠ {c}")
    if intent.get("exclusions"):
        parts.append("USER EXPLICITLY REJECTS:")
        for e in intent["exclusions"][:4]:
            parts.append(f"  ✗ {e}")
    if intent.get("budget"):
        parts.append(f"BUDGET: {intent['budget']}")
    return "\n".join(parts) if parts else ""


def generate_rubric(category: str, criteria: list[dict], profile: dict) -> dict:
    """Build a weighted rubric from criteria + profile."""
    criteria_text = "\n".join(
        f"- {c['name']}: {c['label']} ({c.get('description', '')})"
        for c in criteria
    )
    prefs = profile.get("preferences_summary", "")
    _skip_tokens = {"[Skipped]", "(skipped)"}
    qa_text = "\n".join(
        f"Q: {qa['question']}\nA: {qa['answer']}"
        for qa in profile.get("interview", [])
        if qa.get("answer", "") not in _skip_tokens
    )

    constraint_block = _build_intent_context(profile)
    constraint_section = (
        f"\n\n{constraint_block}\n\n"
        "For criteria directly related to the above constraints, weight them 9-10. "
        "For criteria violating exclusions, weight them 1-2 to penalize."
    ) if constraint_block else ""

    prompt = f"""Category: {category}

Criteria to weight:
{criteria_text}

User's preferences summary:
{prefs}{constraint_section}

Full interview Q&A:
{qa_text}

Build the weighted rubric."""

    raw = run_agent("rubric_generator", user_prompt=prompt, system=GEN_SYSTEM)
    try:
        from llm_client import _try_repair_json
        data = _try_repair_json(raw)
        weighted = data.get("weighted_criteria", [])
    except Exception:
        _logger.warning("[rubric] JSON parse failed, using defaults")
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


def _extract_criterion_relevant_snippet(text: str, criteria: list[dict], max_chars: int = 5000) -> str:
    """
    Select the most criterion-relevant paragraphs from research text instead of naive head truncation.
    Scores each paragraph by how many criterion label/name keywords it contains,
    then assembles top-scoring paragraphs in original order up to max_chars.
    """
    if not text:
        return "(no research yet)"
    if len(text) <= max_chars:
        return text

    # Build keyword set from criterion labels and snake_case names
    keywords: set[str] = set()
    for c in criteria:
        for word in re.findall(r'\b\w{4,}\b', (c.get("label", "") + " " + c.get("name", "")).lower()):
            keywords.add(word)

    if not keywords:
        return text[:max_chars]

    paragraphs = re.split(r'\n\s*\n', text)

    # Score each paragraph by keyword hits
    scored: list[tuple[int, int, str]] = []
    for i, para in enumerate(paragraphs):
        para_lower = para.lower()
        hits = sum(1 for kw in keywords if kw in para_lower)
        scored.append((hits, i, para))

    # Sort by relevance (desc), then original position (asc) as tiebreak
    scored.sort(key=lambda x: (-x[0], x[1]))

    # Collect top paragraphs up to max_chars (preserving selection set)
    selected_indices: set[int] = set()
    total = 0
    for _hits, idx, para in scored:
        if total + len(para) + 2 > max_chars:
            break
        selected_indices.add(idx)
        total += len(para) + 2

    # Reconstruct in original paragraph order
    kept = [para for i, para in enumerate(paragraphs) if i in selected_indices]
    return "\n\n".join(kept) if kept else text[:max_chars]


def fill_criterion_gaps(
    rubric: dict,
    category: str,
    profile: dict,
    research_summary: str = "",
    user_context: str | None = None,
) -> dict:
    """
    For criteria in the rubric that have default rationales ("not addressed in interview"),
    re-infer weights using category norms + research data instead of leaving them at 5.

    This eliminates the "all defaults are 5" problem when interview can't cover all criteria.

    user_context: pre-built context string from _build_analyzer_hint(profile).
    When provided, uses it (includes structured intent). Falls back to preferences_summary.
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

    _logger.info("[rubric] inferring weights for %d unaddressed criteria...", len(defaulted))

    # Build prompt
    defaulted_text = "\n".join(
        f"- {c['name']}: {c['label']} ({c.get('description', '')})"
        for c in defaulted
    )
    # Phase 4: use pre-built intent-aware context when available
    prefs = user_context if user_context is not None else profile.get("preferences_summary", "")
    research_snippet = _extract_criterion_relevant_snippet(research_summary, defaulted, max_chars=5000)

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
        _logger.warning("[rubric] gap-fill failed (%s), keeping defaults", e)
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
        _logger.info("[rubric] inferred weights applied to %d criteria", updated_count)
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