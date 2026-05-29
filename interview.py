"""
Ontology interview.

Asks the user 4-6 smart questions to build a personal profile for this category.
Questions are generated adaptively based on the criteria and previous answers.

Profile is saved as profiles/<category>.json so future runs can reuse it.
"""

import json
import logging
import os
from pathlib import Path
from datetime import datetime
from agents import run_agent
from category import category_to_filename

_logger = logging.getLogger(__name__)


PROFILES_DIR = Path(__file__).parent / "profiles"
PROFILES_DIR.mkdir(exist_ok=True)

# Dynamic interview: ask until coverage is good or hard cap reached
MAX_QUESTIONS = 14          # safety cap, never exceed
MIN_QUESTIONS = 3           # always ask at least this many
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
    "electronics/keyboard-mechanical": [
        "What will you use it for most - typing, coding, gaming, or a mix?",
        "Which layout do you prefer - full-size, TKL, 75%, 65%, or compact?",
        "Switch preference - linear, tactile, clicky, or not sure yet?",
        "Do you need wireless/Bluetooth, or is wired fine?",
        "How important is noise level - quiet enough for shared spaces, or any sound is okay?",
        "Do you care about hot-swappable switches or customizability?",
        "Any must-have features like RGB, macro keys, knob, or software support?",
        "What's your budget range?",
    ],
    "electronics/keyboard": [
        "What will you use it for most - typing, coding, gaming, or a mix?",
        "Do you specifically want mechanical switches, low-profile keys, or a quieter membrane/scissor keyboard?",
        "Which layout do you prefer - full-size, TKL, 75%, 65%, or compact?",
        "Do you need wireless/Bluetooth, or is wired fine?",
        "How important is noise level - quiet enough for shared spaces, or any sound is okay?",
        "Any must-have features like RGB, macro keys, knob, or software support?",
        "Do you need compatibility with Windows, macOS, iPad, or multiple devices?",
        "What's your budget range?",
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
    # Specific-prefix match only. Avoid matching broad domains like
    # electronics/* to whichever electronics template appears first.
    for key, questions in CATEGORY_QUESTION_TEMPLATES.items():
        if cat.startswith(f"{key}/") or cat.startswith(f"{key}-"):
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


def generate_next_question(
    category: str,
    criteria: list[dict],
    previous_qa: list[dict],
    initial_query: str = "",
    memory_context: list[dict] | None = None,
) -> dict:
    """
    Returns {question, why_asking, targets_criterion, is_done}.
    Serves category-template questions first, then coverage-aware dynamic questions.
    initial_query: the user's original search prompt — used to skip already-answered template questions.
    memory_context: signals from past searches — criteria already answered by memory are deprioritised.
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

    # Memory context: tell the interviewer what we already know from past searches so it
    # doesn't ask redundant questions about criteria memory already covers.
    memory_note = ""
    if memory_context:
        remembered_facts = [s.get("text", "") for s in memory_context if s.get("text")]
        if remembered_facts:
            facts_text = "\n".join(f"  - {f}" for f in remembered_facts[:6])
            memory_note = (
                f"\nKNOWN FROM PAST SEARCHES (do NOT ask about these — already answered):\n"
                f"{facts_text}\n"
                f"Focus questions on criteria NOT already covered by the above facts.\n"
            )

    prompt = f"""Category: {category}

All buying criteria for this category:
{criteria_text}
{initial_context}{memory_note}
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

    # W-04: dedup guard — if LLM loops back to an already-targeted criterion after MIN_QUESTIONS, declare done
    if not data.get("is_done") and len(previous_qa) >= MIN_QUESTIONS:
        tc = data.get("targets_criterion", "")
        if tc and tc != "general":
            already_targeted = {qa.get("targets_criterion") for qa in previous_qa} - {None, "", "general"}
            if tc in already_targeted:
                print(f"[interview] W04: LLM re-targeted '{tc}' already covered — forcing is_done=True")
                return {"question": "", "why_asking": "", "targets_criterion": tc, "is_done": True}

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
            dyn_target = _dynamic_coverage_target(len(criteria))
            if coverage >= dyn_target:
                print(f"[interview] coverage at {coverage*100:.0f}% ≥ dynamic target "
                      f"{dyn_target*100:.0f}% ({len(criteria)} criteria) — sufficient, ending")
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

    # Build profile from Q&A — single LLM call for both text and structured intent
    prefs_summary, intent = _summarize_and_extract_intent(category, qa_history)
    profile = {
        "interview": qa_history,
        "preferences_summary": prefs_summary,
        "intent": intent,
        "uncovered_criteria": uncovered,
        "coverage_percent": coverage_pct,
    }
    save_profile(category, profile)
    return profile


# ---- Summarizer constants ----

# Both CLI ("(skipped)") and web ("[Skipped]") skip tokens
_SKIP_ANSWER_TOKENS = frozenset({"[Skipped]", "(skipped)"})


def _categorize_qa_entry(qa: dict) -> str:
    """Return 'skipped' if the user skipped this question, else 'answered'."""
    return "skipped" if qa.get("answer", "") in _SKIP_ANSWER_TOKENS else "answered"


SUMMARIZE_SYSTEM = """You extract structured intent AND produce a readable summary from a product research interview.

Return ONLY this JSON (no markdown, no wrapping text):
{
  "hard_constraints": ["short constraint phrase"],
  "budget": "exact budget string or null",
  "preferences": ["clearly stated preference"],
  "exclusions": ["explicitly rejected feature, brand, or type"],
  "uncertainties": ["tentative statement"],
  "summary_text": "• bullet 1\\n• bullet 2"
}

EXTRACTION RULES:
1. hard_constraints: ONLY MUST/NEVER/required/allergic/can't/won't entries. Keep each under 10 words.
2. budget: exact amount+currency if stated (e.g. "under ₹5000", "$200 max"), else null.
3. preferences: clearly stated wants that are NOT constraints. Skip vague entries like "good quality".
4. exclusions: explicit rejections softer than hard constraints ("prefers not in-ear", "avoids brand X").
5. uncertainties: hedged statements — "maybe", "I think", "I guess", "probably", "not sure but".
6. SKIP SEMANTICS: skipped = UNKNOWN. Never infer from skipped questions.
7. CONTRADICTION: same topic, conflicting answers → LATER answer wins. Note it in summary_text.
8. summary_text: 4-8 bullets, plain text. Order: [REQUIRED]/[EXCLUDED] → Budget → Preferences → Tentative.

JSON only. No commentary."""


# ---- Priority context for process_message classifier ----

_CRITICAL_CONTEXT_KEYWORDS = frozenset({
    "budget", "price", "cost", "spend", "rupee", "dollar", "rs.", "₹", "$",
    "allerg", "medical", "condition", "never", "must", "required", "can't", "cannot",
    "exclud", "avoid", "hate", "worst", "won't", "refuse",
})


def _build_priority_classifier_context(qa_history: list[dict], max_entries: int = 6) -> str:
    """
    Build classifier context window with semantic priority.
    Always includes budget/constraint entries; fills remaining slots with recency.
    """
    if not qa_history:
        return "(none yet)"

    critical_idxs: set[int] = set()
    for i, qa in enumerate(qa_history):
        combined = (qa.get("question", "") + " " + qa.get("answer", "")).lower()
        if any(kw in combined for kw in _CRITICAL_CONTEXT_KEYWORDS):
            critical_idxs.add(i)

    remaining = max_entries - len(critical_idxs)
    recent_idxs = [i for i in range(len(qa_history) - 1, -1, -1)
                   if i not in critical_idxs][:max(0, remaining)]
    selected = sorted(critical_idxs | set(recent_idxs))

    return "\n".join(
        f"Q: {qa_history[i]['question']}\nA: {qa_history[i]['answer']}"
        for i in selected
    )


# ---- Dynamic coverage target ----

def _dynamic_coverage_target(n_criteria: int) -> float:
    """
    Scale COVERAGE_TARGET down for large criteria sets.
    With 5 criteria: 90% target (4-5 questions) is achievable.
    With 12+ criteria: 90% would need 11+ questions, hitting MAX_QUESTIONS prematurely.
    """
    if n_criteria <= 5:
        return COVERAGE_TARGET   # 0.90
    elif n_criteria <= 8:
        return 0.75
    elif n_criteria <= 12:
        return 0.65
    else:
        return 0.60


PROCESS_MESSAGE_SYSTEM = """You are an adaptive interview assistant classifying user messages during a product research interview.

TASK: Classify what the user said and generate the appropriate response.

INTENTS:
ANSWER  — Clear preference signal (even brief/partial). Extract it cleanly.
QUESTION — User asks what a term means, wants an explanation, or asks a clarifying question about the topic.
MIXED   — Contains BOTH a preference AND a clarifying question in the same message.
SKIP    — No preference / wants to skip: "skip", "don't care", "anything", "doesn't matter", "no idea", "not sure".
COMMAND — Wants to end the interview: "recommend now", "show results", "enough questions", "stop asking", "done".
UNCLEAR — Too vague to extract a preference: single "yes"/"maybe"/"ok" with no context, contradictions, non-sequiturs.

RULES:
- Prefer ANSWER over UNCLEAR when there's any preference signal, even partial
- "I want something balanced" → UNCLEAR (too vague, needs narrowing)
- "Camera should be decent" → UNCLEAR (decent is undefined — needs: social/video/low-light/casual?)
- "I play games sometimes" → UNCLEAR (needs: major priority or occasional?)
- "Gaming matters most, but what is refresh rate?" → MIXED (clear preference + question)
- "What is OLED?" → QUESTION (pure question)
- "I mainly care about camera and battery" → ANSWER

For QUESTION and MIXED: 2-3 sentence plain-language explanation. No markdown. No extra text.
For UNCLEAR: generate a clarification follow-up with 3-4 specific bullet-point options.
For ANSWER/MIXED: extract the preference in 1 clean sentence (strip out the question part for MIXED).

Return ONLY valid JSON (no markdown, no commentary):
{
  "intent": "ANSWER|QUESTION|MIXED|SKIP|COMMAND|UNCLEAR",
  "confidence": 0.0-1.0,
  "preference_fragment": "1-sentence preference or null",
  "question_answer": "plain-language explanation or null",
  "clarification_question": "follow-up with specific options or null",
  "command_action": "finish or null"
}"""


_SKIP_EXACT = frozenset({
    "skip", "next", "idc", "i don't care", "dont care", "no preference", "no pref",
    "anything", "anything is fine", "doesn't matter", "doesnt matter", "no idea",
    "not sure", "not important", "pass", "no strong preference", "i don't mind",
})

_COMMAND_EXACT = frozenset({
    "recommend now", "show results", "enough questions", "done interviewing",
    "start research", "stop interview", "show recommendations", "go ahead",
    "enough", "stop asking", "just recommend", "recommend",
})


def process_message(
    category: str,
    criteria: list[dict],
    current_question: dict,
    message: str,
    qa_history: list[dict],
) -> dict:
    """
    Classify a user's interview message and return the appropriate action.

    Returns dict with keys:
        intent              : ANSWER | QUESTION | MIXED | SKIP | COMMAND | UNCLEAR
        confidence          : float 0-1
        preference_fragment : cleaned answer string (ANSWER/MIXED) or None
        question_answer     : plain-language answer to user's question (QUESTION/MIXED) or None
        clarification_question : targeted follow-up (UNCLEAR) or None
        command_action      : "finish" (COMMAND) or None
    """
    msg = message.strip()
    lower = msg.lower()

    # Fast-path: unambiguous skip/command → skip LLM call
    if lower in _SKIP_EXACT:
        return {"intent": "SKIP", "confidence": 1.0, "preference_fragment": None,
                "question_answer": None, "clarification_question": None, "command_action": None}

    if lower in _COMMAND_EXACT:
        return {"intent": "COMMAND", "confidence": 1.0, "preference_fragment": None,
                "question_answer": None, "clarification_question": None, "command_action": "finish"}

    # Build LLM context: criteria summary + priority history (budget/constraints always included)
    criteria_text = "\n".join(
        f"- {c['name']}: {c.get('label', '')} — {c.get('description', '')}"
        for c in criteria
    )
    qa_summary = _build_priority_classifier_context(qa_history, max_entries=6)

    prompt = f"""Category: {category}
Current interview question: "{current_question.get('question', '')}"
User's message: "{msg}"

Available criteria (for disambiguation context):
{criteria_text}

Recent previous answers:
{qa_summary}

Classify the user's message and generate the appropriate response."""

    try:
        raw = run_agent("interview_classifier", user_prompt=prompt, system=PROCESS_MESSAGE_SYSTEM)
        from llm_client import _try_repair_json
        data = _try_repair_json(raw)
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict, got {type(data).__name__}")
        return {
            "intent": data.get("intent", "ANSWER"),
            "confidence": float(data.get("confidence", 0.8)),
            "preference_fragment": data.get("preference_fragment") or None,
            "question_answer": data.get("question_answer") or None,
            "clarification_question": data.get("clarification_question") or None,
            "command_action": data.get("command_action") or None,
        }
    except Exception as e:
        print(f"[interview] process_message failed: {e} — treating as ANSWER")
        return {"intent": "ANSWER", "confidence": 0.5, "preference_fragment": msg,
                "question_answer": None, "clarification_question": None, "command_action": None}


_EMPTY_INTENT: dict = {
    "hard_constraints": [],
    "budget": None,
    "preferences": [],
    "exclusions": [],
    "uncertainties": [],
}


def _summarize_and_extract_intent(
    category: str,
    qa_history: list[dict],
) -> tuple[str, dict]:
    """
    Single LLM call producing both a human-readable summary string AND a
    structured intent dict. This replaces the old plain-text summarizer.

    Returns (summary_text: str, intent: dict).
    The intent dict has keys: hard_constraints, budget, preferences, exclusions, uncertainties.
    """
    if not qa_history:
        return "No preferences specified.", dict(_EMPTY_INTENT)

    answered = [qa for qa in qa_history if _categorize_qa_entry(qa) == "answered"]
    skipped_count = len(qa_history) - len(answered)

    if not answered:
        return "No preferences specified (all questions skipped).", dict(_EMPTY_INTENT)

    qa_text = "\n".join(f"Q: {qa['question']}\nA: {qa['answer']}" for qa in answered)
    skip_note = (
        f"\n\nNote: {skipped_count} question(s) skipped — treat as UNKNOWN, never infer."
        if skipped_count > 0 else ""
    )
    prompt = (
        f"Category: {category}\n\nInterview Q&A:\n{qa_text}{skip_note}"
        f"\n\nExtract structured summary."
    )

    try:
        raw = run_agent("preference_summarizer", user_prompt=prompt, system=SUMMARIZE_SYSTEM)
        from llm_client import _try_repair_json
        data = _try_repair_json(raw)
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict, got {type(data).__name__}")

        summary_text = data.get("summary_text") or ""
        if not isinstance(summary_text, str):
            summary_text = str(summary_text)

        def _clean_strs(lst) -> list[str]:
            return [s.strip() for s in (lst or []) if isinstance(s, str) and s.strip()]

        intent = {
            "hard_constraints": _clean_strs(data.get("hard_constraints")),
            "budget": (
                data["budget"].strip()
                if isinstance(data.get("budget"), str) and data["budget"].strip()
                else None
            ),
            "preferences": _clean_strs(data.get("preferences")),
            "exclusions": _clean_strs(data.get("exclusions")),
            "uncertainties": _clean_strs(data.get("uncertainties")),
        }

        if not summary_text:
            # Fallback: reconstruct minimal text from structured fields
            lines = []
            for c in intent["hard_constraints"]:
                lines.append(f"• [REQUIRED] {c}")
            if intent["budget"]:
                lines.append(f"• Budget: {intent['budget']}")
            for p in intent["preferences"]:
                lines.append(f"• {p}")
            summary_text = "\n".join(lines) if lines else "No preferences specified."

        return summary_text.strip(), intent

    except Exception as exc:
        _logger.warning("[interview] summarize+intent failed (%s) — using text fallback", exc)
        # Last resort: plain-text-only summarization without structure
        return _summarize_preferences_text_only(category, qa_history), dict(_EMPTY_INTENT)


def _summarize_preferences_text_only(category: str, qa_history: list[dict]) -> str:
    """
    Fallback: plain-text summarizer using the old single-field approach.
    Called only when the JSON-structured summarizer fails.
    """
    answered = [qa for qa in qa_history if _categorize_qa_entry(qa) == "answered"]
    if not answered:
        return "No preferences specified (all questions skipped)."
    qa_text = "\n".join(f"Q: {qa['question']}\nA: {qa['answer']}" for qa in answered)
    _SIMPLE_SYSTEM = (
        "Summarize the user's stated product preferences as 4-8 short bullet points. "
        "Put [REQUIRED] before hard constraints. Put Budget first if mentioned. Plain text only."
    )
    try:
        return run_agent("preference_summarizer", user_prompt=qa_text, system=_SIMPLE_SYSTEM).strip()
    except Exception as e:
        return f"(Could not summarize: {e})"


def _summarize_preferences(category: str, qa_history: list[dict]) -> str:
    """Backward-compatible wrapper — returns text summary only."""
    text, _ = _summarize_and_extract_intent(category, qa_history)
    return text


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

    prefs_summary, intent = _summarize_and_extract_intent(category, updated_history)
    profile = {
        "interview": updated_history,
        "preferences_summary": prefs_summary,
        "intent": intent,
    }
    save_profile(category, profile)
    return profile
