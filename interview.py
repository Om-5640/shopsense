"""
Ontology interview.

Asks the user 4-6 smart questions to build a personal profile for this category.
Questions are generated adaptively based on the criteria and previous answers.

Profile is saved as profiles/<category>.json so future runs can reuse it.
"""

import json
import os
from pathlib import Path
from datetime import datetime
from agents import run_agent
from category import category_to_filename


PROFILES_DIR = Path(__file__).parent / "profiles"
PROFILES_DIR.mkdir(exist_ok=True)

# Dynamic interview: ask until coverage is good or hard cap reached
MAX_QUESTIONS = 14          # safety cap, never exceed
MIN_QUESTIONS = 8           # always ask at least this many
COVERAGE_TARGET = 0.90      # stop when 90% of criteria addressed


# ---- Category-specific mandatory question templates ----
# These are asked first (in shuffled order) before dynamic criteria-based questions.
# Keys are category slug prefixes (matched with startswith).

CATEGORY_QUESTION_TEMPLATES: dict[str, list[str]] = {
    "skincare": [
        "What's your skin type — oily, dry, combination, or sensitive?",
        "What are your main skin concerns? (e.g. acne, pigmentation, dullness, uneven tone)",
        "Do you have any known allergies or ingredients you avoid? (e.g. fragrance, alcohol, parabens)",
        "What's your current skincare routine like — minimal, moderate, or elaborate?",
        "Do you prefer fragrance-free products, or is a pleasant scent a bonus?",
        "What's your approximate budget per product?",
        "What climate do you live in — humid, dry, cold, or tropical?",
        "Roughly how old are you? (teens, 20s, 30s, 40s+)",
    ],
    "electronics/earbuds": [
        "Where will you use these most — commuting, gym, office, or home?",
        "Do you need active noise cancellation, or is passive isolation enough?",
        "Sound preference — more bass, balanced, or vocal clarity?",
        "How important is call quality and microphone performance?",
        "Battery life priority — how many hours between charges do you need?",
        "In-ear comfort is personal — do you have any fit issues with standard ear tips?",
        "Which devices will you mainly pair with — Android, iPhone, laptop?",
        "What's your budget range?",
    ],
    "electronics/headphones": [
        "Over-ear or on-ear preference?",
        "Primary use: music listening, gaming, calls, or travel?",
        "Do you need active noise cancellation?",
        "Wired or wireless — or either?",
        "Sound signature preference — bass-heavy, balanced, or bright?",
        "How important is comfort for multi-hour sessions?",
        "Budget range?",
        "Any specific ecosystem to match (Xbox, PlayStation, Mac)?",
    ],
    "electronics/laptop": [
        "Primary use: coding, video editing, office work, gaming, or general use?",
        "How important is portability? Do you carry it daily?",
        "Windows or macOS — or open to either?",
        "How long must the battery last on a single charge?",
        "Screen size preference — 13\", 15\", or 17\"?",
        "Do you need dedicated GPU for graphics/gaming?",
        "Budget range?",
        "Any specific ports you must have (HDMI, USB-A, SD card)?",
    ],
    "electronics/phone": [
        "Android or iOS?",
        "Camera the top priority, or more balanced?",
        "Battery life or thin/light design — which wins if you must choose?",
        "How important is 5G support?",
        "Screen size preference — compact (~6\") or large (~6.7\")?",
        "Budget range?",
        "Any specific features critical for you (stylus, satellite SOS, IP68)?",
        "How long do you typically keep a phone before upgrading?",
    ],
    "electronics/monitor": [
        "Primary use: gaming, creative work, coding, or general office?",
        "Screen size preference?",
        "Resolution priority: 1080p, 1440p, or 4K?",
        "Panel type preference: IPS (colors), VA (contrast), TN (speed)?",
        "Refresh rate needed — 60Hz, 144Hz, or 240Hz+?",
        "Ergonomic adjustability important (height, pivot)?",
        "Budget range?",
        "Any connectivity requirements (USB-C PD, HDMI 2.1)?",
    ],
    "bedding/mattress": [
        "What's your primary sleeping position — side, back, stomach, or combo?",
        "Do you sleep hot or cold?",
        "Firmness preference — soft, medium, or firm?",
        "Do you have a partner, and is motion isolation important?",
        "Any back pain or joint issues that affect what you need?",
        "Budget range?",
        "Allergies to latex or specific materials?",
        "How important is a trial period / returns policy?",
    ],
    "watches": [
        "Analog, smartwatch, or fitness tracker?",
        "Primary use: everyday wear, sports, formal occasions, or all?",
        "Case size preference — smaller (~38mm) or larger (~44mm+)?",
        "Movement preference: automatic, quartz, or smart?",
        "Budget range?",
        "Water resistance needed?",
        "Any brand preferences or things to avoid?",
        "Will you wear it to formal events or just casual?",
    ],
    "kitchen": [
        "What will you cook most — Indian, continental, baking, or everything?",
        "Family size — cooking for how many people typically?",
        "How much counter or storage space is available?",
        "Daily use or occasional?",
        "Any power / wattage constraints?",
        "Budget range?",
        "Brand preferences or things to avoid?",
        "Most important feature — speed, capacity, ease of cleaning, or durability?",
    ],
    "footwear": [
        "Primary activity — running, walking, gym training, casual, or formal?",
        "Any foot conditions — flat feet, wide feet, plantar fasciitis, overpronation?",
        "Terrain: road, trail, treadmill, or mixed?",
        "Cushioning preference — maximal, moderate, or minimal (ground feel)?",
        "Budget range?",
        "Brand loyalty or anything to avoid?",
        "How many km/miles per week would you use these?",
        "Any specific fit concerns — narrow/wide toe box?",
    ],
    "furniture/chair": [
        "Primary use — work-from-home all day, gaming, or occasional seating?",
        "Any existing back/neck/posture issues to work around?",
        "Body type / height to consider for sizing?",
        "Lumbar support or full back support more important?",
        "Armrest adjustability needed?",
        "Budget range?",
        "Material preference — mesh (cooling) or foam/leather (comfort)?",
        "How many hours per day will you sit in it?",
    ],
}


def _get_template_questions(category: str) -> list[str]:
    """Return mandatory question list for this category, or [] if no template."""
    cat = category.lower()
    # Exact match first
    if cat in CATEGORY_QUESTION_TEMPLATES:
        return list(CATEGORY_QUESTION_TEMPLATES[cat])
    # Prefix match
    for key, questions in CATEGORY_QUESTION_TEMPLATES.items():
        if cat.startswith(key) or key.startswith(cat.split("/")[0]):
            return list(questions)
    return []


# ---- profile storage ----

def profile_path(category: str) -> Path:
    return PROFILES_DIR / f"{category_to_filename(category)}.json"


def load_profile(category: str) -> dict | None:
    """Returns profile dict or None if not found / corrupt."""
    path = profile_path(category)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_profile(category: str, profile: dict) -> None:
    """Save profile to disk."""
    path = profile_path(category)
    profile["category"] = category
    profile["last_updated"] = datetime.utcnow().isoformat() + "Z"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2)
    print(f"[profile] saved to {path}")


# ---- question generation ----

def _query_answers_template(template_q: str, query: str) -> bool:
    """Returns True if the initial query already contains an answer to the template question."""
    if not query:
        return False
    import re
    q_lower = template_q.lower()
    query_lower = query.lower()

    # Budget / price range questions — any currency or "under/below/within N"
    if any(kw in q_lower for kw in ["budget", "price range", "how much", "spend", "budget range"]):
        price_patterns = [
            r'₹\s*\d+', r'rs\.?\s*\d+', r'inr\s*\d+',
            r'under\s+\d+', r'below\s+\d+', r'within\s+\d+', r'upto\s+\d+',
            r'\d[\d,]+\s*(?:rupee|rs|inr)',
            r'\$\s*\d+', r'usd\s*\d+',
            r'£\s*\d+', r'gbp\s*\d+',
            r'€\s*\d+', r'eur\s*\d+',
            r'\d+k\b',
        ]
        return any(re.search(p, query_lower) for p in price_patterns)

    # Watch type — "Analog, smartwatch, or fitness tracker?"
    if "analog" in q_lower and "smartwatch" in q_lower:
        return any(kw in query_lower for kw in [
            "analog", "analogue", "smartwatch", "smart watch", "digital", "fitness tracker", "sports watch"
        ])

    # Phone platform — "Android or iOS?"
    if "android" in q_lower and "ios" in q_lower:
        return any(kw in query_lower for kw in [
            "android", "ios", "iphone", "samsung", "oneplus", "pixel", "realme", "redmi", "poco"
        ])

    # Wired vs wireless
    if "wired" in q_lower and "wireless" in q_lower:
        return any(kw in query_lower for kw in ["wired", "wireless", "bluetooth", "tws"])

    # Noise cancellation
    if "noise cancellation" in q_lower or ("active noise" in q_lower):
        return any(kw in query_lower for kw in ["anc", "noise cancel", "active noise"])

    # Over-ear vs on-ear headphones
    if "over-ear" in q_lower and "on-ear" in q_lower:
        return any(kw in query_lower for kw in ["over-ear", "over ear", "on-ear", "on ear", "in-ear"])

    # Gender / intended user
    if any(kw in q_lower for kw in ["gender", "for whom", "who will"]):
        return any(kw in query_lower for kw in ["men", "man", "women", "woman", "boy", "girl", "kids", "child"])

    return False


def _get_next_template_question(category: str, asked_questions: list[str], initial_query: str = "") -> str | None:
    """Return the next unanswered template question, or None if all done."""
    templates = _get_template_questions(category)
    if not templates:
        return None
    asked_lower = {q.lower().strip() for q in asked_questions}
    for q in templates:
        # Check if a semantically close question was already asked (simple keyword check)
        q_words = set(q.lower().split())
        already_asked = any(
            len(q_words & set(asked.split())) / max(len(q_words), 1) > 0.5
            for asked in asked_lower
        )
        if already_asked:
            continue
        # Skip questions the user already answered in their initial query
        if initial_query and _query_answers_template(q, initial_query):
            continue
        return q
    return None


QUESTION_SYSTEM = """You are a thoughtful interviewer helping a user find the perfect product for THEIR situation.

You ask one question at a time. Each question must:
1. Be SPECIFIC - never "what do you want?", always "do you prefer X or Y?"
2. Be HIGH-SIGNAL - the answer should significantly affect product ranking
3. Build on previous answers - if user said "I run hot" already, don't ask about temperature again
4. Feel like a friend asking, not a survey form
5. Allow for nuance in the answer
6. TARGET UNADDRESSED CRITERIA - prioritize asking about criteria the user hasn't covered yet

Return ONLY a JSON object:
{
  "question": "Your question text here",
  "why_asking": "Brief internal note on why this matters",
  "targets_criterion": "snake_case_id of the criterion this question is about (or 'general' if cross-cutting)",
  "is_done": false
}

Set is_done=true only when 90%+ of criteria are addressed. Don't ask redundant questions. If you've already asked 10+ questions, strongly consider is_done=true unless critical criteria remain uncovered. Never ask two questions that target the same user context.

NO markdown, NO commentary, JSON only."""


def _identify_uncovered_criteria(criteria: list[dict], qa_history: list[dict]) -> list[str]:
    """Returns the list of criterion names not yet targeted by any question."""
    targeted = {qa.get("targets_criterion") for qa in qa_history}
    targeted.discard(None)
    targeted.discard("")
    targeted.discard("general")
    return [c["name"] for c in criteria if c["name"] not in targeted]


def generate_next_question(category: str, criteria: list[dict], previous_qa: list[dict], initial_query: str = "") -> dict:
    """
    Returns {question, why_asking, targets_criterion, is_done}.
    Serves category-template questions first, then coverage-aware dynamic questions.
    initial_query: the user's original search prompt — used to skip already-answered template questions.
    """
    # ---- Serve template questions first ----
    asked_questions = [qa["question"] for qa in previous_qa]
    template_q = _get_next_template_question(category, asked_questions, initial_query)
    if template_q and len(previous_qa) < MIN_QUESTIONS:
        return {
            "question": template_q,
            "why_asking": "Category-specific essential context",
            "targets_criterion": "general",
            "is_done": False,
        }

    criteria_text = "\n".join(f"- {c['name']}: {c['label']} ({c['description']})" for c in criteria)
    qa_text = "\n".join(
        f"Q: {qa['question']}\nA: {qa['answer']}\n(targeted: {qa.get('targets_criterion', '?')})"
        for qa in previous_qa
    ) if previous_qa else "(none yet)"

    uncovered = _identify_uncovered_criteria(criteria, previous_qa)
    coverage_pct = round((len(criteria) - len(uncovered)) / max(len(criteria), 1) * 100)

    coverage_note = ""
    if uncovered:
        coverage_note = (
            f"\nUNCOVERED CRITERIA (prioritize these): {', '.join(uncovered)}\n"
            f"Current coverage: {coverage_pct}% ({len(criteria) - len(uncovered)}/{len(criteria)})"
        )
    else:
        coverage_note = f"\nAll criteria covered ({coverage_pct}%). Set is_done=true unless you see a critical gap."

    initial_context = ""
    if initial_query:
        initial_context = (
            f"\nUser's original search query (already-stated context — "
            f"DO NOT ask about anything already answered in it, e.g. budget, product type, brand): "
            f"{initial_query}\n"
        )

    prompt = f"""Category: {category}

All buying criteria for this category:
{criteria_text}
{initial_context}
Previous questions asked and answers given:
{qa_text}
{coverage_note}

Generate the next question (or set is_done=true if coverage is sufficient)."""

    try:
        raw = run_agent("interview_questioner", user_prompt=prompt, system=QUESTION_SYSTEM)
        from llm_client import _try_repair_json
        data = _try_repair_json(raw)
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict, got {type(data).__name__}")
    except Exception as e:
        print(f"[interview] question gen failed: {e}")
        return {"question": "", "why_asking": "", "targets_criterion": "", "is_done": True}

    return {
        "question": data.get("question", ""),
        "why_asking": data.get("why_asking", ""),
        "targets_criterion": data.get("targets_criterion", ""),
        "is_done": bool(data.get("is_done", False)),
    }


# ---- run the interview ----

def run_interview(category: str, criteria: list[dict]) -> dict:
    """
    Conducts the CLI interview. Returns a profile dict.
    Dynamic length: stops when criteria coverage hits target, capped at MAX_QUESTIONS.
    """
    print(f"\n{'─'*72}")
    print(f"  Quick interview to personalize results for {category}")
    print(f"  I'll ask up to {MAX_QUESTIONS} questions targeting your {len(criteria)} criteria.")
    print(f"  Answer honestly, brief is fine. Type 'skip' to skip any question.")
    print(f"{'─'*72}\n")

    qa_history = []

    for i in range(MAX_QUESTIONS):
        # Force at least MIN_QUESTIONS before allowing is_done
        force_continue = (i + 1) < MIN_QUESTIONS

        # Check coverage independently - stop if we've targeted enough criteria
        if not force_continue:
            uncovered = _identify_uncovered_criteria(criteria, qa_history)
            coverage = (len(criteria) - len(uncovered)) / max(len(criteria), 1)
            if coverage >= COVERAGE_TARGET:
                print(f"[interview] coverage at {coverage*100:.0f}% — sufficient, ending")
                break

        result = generate_next_question(category, criteria, qa_history)

        if result["is_done"] and not force_continue:
            print(f"[interview] LLM signaled done after {i} questions")
            break

        if not result["question"]:
            print("[interview] no question generated, ending")
            break

        targets = result.get("targets_criterion", "")
        target_tag = f" [→ {targets}]" if targets and targets != "general" else ""
        print(f"Q{i + 1}{target_tag}: {result['question']}")
        try:
            answer = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[interview] interrupted")
            break

        if not answer or answer.lower() == "skip":
            answer = "(skipped)"
        elif answer.lower() in {"quit", "exit"}:
            print("[interview] exiting")
            break

        qa_history.append({
            "question": result["question"],
            "answer": answer,
            "why_asked": result["why_asking"],
            "targets_criterion": result.get("targets_criterion", ""),
        })
        print()

    # Final coverage report
    uncovered = _identify_uncovered_criteria(criteria, qa_history)
    coverage_pct = round((len(criteria) - len(uncovered)) / max(len(criteria), 1) * 100)
    print(f"[interview] final coverage: {coverage_pct}% ({len(qa_history)} questions asked)")
    if uncovered:
        print(f"[interview] uncovered criteria will be inferred from research: {', '.join(uncovered)}")

    # Build profile from Q&A
    profile = {
        "interview": qa_history,
        "preferences_summary": _summarize_preferences(category, qa_history),
        "uncovered_criteria": uncovered,
        "coverage_percent": coverage_pct,
    }
    save_profile(category, profile)
    return profile


def _summarize_preferences(category: str, qa_history: list[dict]) -> str:
    """Distill the interview into a tight summary for use in rubric generation."""
    if not qa_history:
        return "No preferences specified."

    qa_text = "\n".join(f"Q: {qa['question']}\nA: {qa['answer']}" for qa in qa_history)
    prompt = f"""User answered these questions about buying a {category}:

{qa_text}

Summarize their preferences in 3-5 short bullet points. Be specific. Plain text, no markdown."""

    try:
        raw = run_agent("preference_summarizer", user_prompt=prompt)
        return raw.strip()
    except Exception as e:
        return f"(Could not summarize: {e})"


# ---- top-level: prompt for use / edit / new ----

def get_or_create_profile(category: str, criteria: list[dict], force_new: bool = False,
                           region: str | None = None) -> dict:
    """
    Top-level entry point.
    Returns a profile, either loaded, edited, or freshly created.

    If `region` is provided and differs from saved profile, updates and saves
    in one operation (avoids duplicate save log spam).
    """
    existing = None if force_new else load_profile(category)

    if existing is not None:
        print(f"\n[profile] Found saved profile for {category}")
        print(f"Last updated: {existing.get('last_updated', '?')}")
        print(f"\nPreferences summary:")
        print(existing.get("preferences_summary", "(none)"))
        print()

        try:
            choice = input("Use this profile? (yes/edit/new) [yes]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            choice = "yes"

        if choice in {"", "yes", "y"}:
            # Update region in-place if changed (single save)
            if region and region != "global" and existing.get("region") != region:
                existing["region"] = region
                save_profile(category, existing)
            return existing
        elif choice in {"edit", "e"}:
            profile = _edit_profile(category, criteria, existing)
        else:
            profile = run_interview(category, criteria)
    else:
        profile = run_interview(category, criteria)

    # Add region BEFORE the final save (avoids second write)
    if region and region != "global":
        profile["region"] = region
        save_profile(category, profile)  # re-save with region included
    return profile


def _edit_profile(category: str, criteria: list[dict], existing: dict) -> dict:
    """
    Lets user add/change answers. Simple approach: show existing Q&A,
    let them re-answer any, then save.
    """
    print(f"\n{'─'*72}")
    print(f"  Editing profile for {category}")
    print(f"  Press Enter to keep an answer, type a new one to replace it.")
    print(f"{'─'*72}\n")

    qa_history = existing.get("interview", [])
    updated_history = []

    for i, qa in enumerate(qa_history, 1):
        print(f"Q{i}: {qa['question']}")
        print(f"Current: {qa['answer']}")
        try:
            new_answer = input(f"New answer (Enter to keep): ").strip()
        except (EOFError, KeyboardInterrupt):
            new_answer = ""
        if new_answer:
            qa["answer"] = new_answer
        updated_history.append(qa)
        print()

    profile = {
        "interview": updated_history,
        "preferences_summary": _summarize_preferences(category, updated_history),
    }
    save_profile(category, profile)
    return profile