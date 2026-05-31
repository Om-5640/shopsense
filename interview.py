"""
Ontology interview.

Asks the user 4-6 smart questions to build a personal profile for this category.
Questions are generated adaptively based on the criteria and previous answers.

Profile is saved as profiles/<category>.json so future runs can reuse it.
"""

import json
import logging
import os
import re as _re
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


# ---- Budget / brand detection helpers ----

_BUDGET_PATTERNS = _re.compile(
    r'₹\s*\d|rs\.?\s*\d|\brs\b|\dinr\b|\d+k\b'
    r'|under\s+\d|below\s+\d|within\s+\d|upto\s+\d'
    r'|\$\s*\d|£\s*\d|€\s*\d'
    r'|\bbudget\b|\bprice\b|\bcost\b|\bspend\b',
    _re.IGNORECASE,
)


def _mentions_budget(text: str) -> bool:
    """True if the text contains a price or budget mention."""
    return bool(_BUDGET_PATTERNS.search(text)) if text else False


def _budget_asked(qa_history: list[dict]) -> bool:
    """True if budget has been covered in prior Q&A."""
    for qa in qa_history:
        combined = (qa.get("question", "") + " " + qa.get("answer", "")).lower()
        if any(kw in combined for kw in ("budget", "price range", "how much", "spend", "rupee", "₹", "$")):
            return True
    return False


def _brand_asked(qa_history: list[dict]) -> bool:
    """True if brand preference has been covered in prior Q&A."""
    for qa in qa_history:
        combined = (qa.get("question", "") + " " + qa.get("answer", "")).lower()
        if any(kw in combined for kw in ("brand", "manufacturer", "prefer", "avoid brand", "company")):
            return True
    return False


def _product_noun(category: str) -> str:
    """'electronics/gaming-mouse' → 'gaming mouse'"""
    parts = category.split("/")
    return parts[-1].replace("-", " ").replace("_", " ")


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

QUESTION_SYSTEM = """You are a knowledgeable friend helping someone buy the right product — NOT a survey bot. You know this product category well.

STRICT PRIORITY ORDER — follow this every time:
1. BUDGET FIRST: If budget hasn't been addressed yet AND is not in the original search query, ask it as your very first question.
   Natural phrasings: "What's your budget range?" / "How much are you looking to spend?" / "Any price range in mind?"
   EXCEPTION: If the user's original search query already states a budget (e.g. "under 3k", "₹50,000", "$200 max"), budget is already answered — skip directly to rule 2.
   This is NON-NEGOTIABLE — the budget shapes which tier of products to recommend.

2. PRIMARY USE CASE: If not obvious from the query, ask how/where they'll use it.
   Right: "Do you mostly game competitively or casually?" / "Is this for commuting, the gym, or work from home?"
   Wrong: "What is your primary intended usage pattern for this product?"

3. MOST IMPORTANT UNCOVERED CRITERION: Pick the single criterion that would most change the recommendation.
   Ask as if you've been researching this product type: specific, informed, natural.
   Right: "Do you need wireless, or is wired fine?" / "How many hours of battery do you need in one session?"
   Wrong: "What are your connectivity preferences?" / "Describe your battery requirements."

4. BRAND PREFERENCE (if not asked within first 4 questions): "Any brands you'd go for — or ones you want to avoid?"

RULES:
- ONE question only. Never combine two questions ("and also...").
- Skip anything already answered in the user's original search query (e.g. if they said "wireless", don't ask about connectivity).
- If memory shows a fact about the user (e.g. they always buy Sony), don't ask again.
- Sound like a friend who knows the product, not a form field.

Return ONLY JSON:
{
  "question": "your single question",
  "why_asking": "one-line internal note: why this matters for ranking",
  "targets_criterion": "criterion_name or 'budget' or 'brand_preference' or 'general'",
  "is_done": false
}

Set is_done=true ONLY when ALL of: budget covered, main use case clear, ≥60% criteria addressed, ≥3 questions asked.
NO markdown, JSON only."""


def _identify_uncovered_criteria(
    criteria: list[dict],
    qa_history: list[dict],
    initial_query: str = "",
) -> list[str]:
    """Returns criterion names not yet covered by a non-skipped answered question.

    A question answered with [Skipped]/(skipped) does NOT count as covered.

    Special rule: price_to_value is implicitly covered whenever the budget is
    known (either stated in the initial query or answered during the interview).
    Budget = what the user can spend; price_to_value = does a product justify its
    price. The rubric generator infers price_to_value context from the budget, so
    asking a separate price_to_value question would be redundant.
    """
    targeted = {
        qa.get("targets_criterion")
        for qa in qa_history
        if qa.get("answer", "") not in _SKIP_ANSWER_TOKENS
    }
    targeted.discard(None)
    targeted.discard("")
    targeted.discard("general")

    # If budget is known from query or Q&A, treat price_to_value as covered
    if _mentions_budget(initial_query) or _budget_asked(qa_history):
        targeted.add("price_to_value")

    return [c["name"] for c in criteria if c["name"] not in targeted]


def generate_next_question(
    category: str,
    criteria: list[dict],
    previous_qa: list[dict],
    initial_query: str = "",
    memory_context: list[dict] | None = None,
    primary_noun: str = "",
) -> dict:
    """
    Returns {question, why_asking, targets_criterion, is_done}.
    Budget is always asked first (unless already in query). All other questions are LLM-driven.
    initial_query: user's original search — used to skip already-answered topics.
    memory_context: signals from past searches.
    primary_noun: exact product name from detection (e.g. "gaming mouse") — overrides _product_noun().
    """
    n = len(previous_qa)

    # ---- Always ask budget first if not mentioned in query and not already asked ----
    if n == 0 and not _mentions_budget(initial_query) and not _budget_asked(previous_qa):
        noun = primary_noun.strip() if primary_noun.strip() else _product_noun(category)
        return {
            "question": f"What's your budget range for this {noun}?",
            "why_asking": "Budget defines which price tier to focus on — the primary filter for all recommendations",
            "targets_criterion": "budget",
            "is_done": False,
        }

    criteria_text = "\n".join(f"- {c['name']}: {c['label']} ({c['description']})" for c in criteria)
    qa_text = "\n".join(
        f"Q: {qa['question']}\nA: {qa['answer']}\n(targeted: {qa.get('targets_criterion', '?')})"
        for qa in previous_qa
    ) if previous_qa else "(none yet)"

    uncovered = _identify_uncovered_criteria(criteria, previous_qa, initial_query)
    coverage_pct = round((len(criteria) - len(uncovered)) / max(len(criteria), 1) * 100)

    if uncovered:
        coverage_note = (
            f"\nUNCOVERED CRITERIA (ask about these next): {', '.join(uncovered)}\n"
            f"Coverage so far: {coverage_pct}% ({len(criteria) - len(uncovered)}/{len(criteria)} criteria addressed)"
        )
    else:
        coverage_note = f"\nAll criteria covered ({coverage_pct}%). Set is_done=true."

    budget_note = ""
    if not _mentions_budget(initial_query) and not _budget_asked(previous_qa):
        budget_note = "\nCRITICAL: Budget has NOT been asked yet — make it your question.\n"
    elif _mentions_budget(initial_query):
        budget_note = (
            "\nCRITICAL: Budget is ALREADY KNOWN from the original search query. "
            "SKIP budget entirely — do NOT ask about price, cost, or spending. "
            "Treat budget as fully answered and move to the next uncovered criterion.\n"
        )

    brand_note = ""
    if n >= 3 and not _brand_asked(previous_qa):
        brand_note = "\nNOTE: Brand preference has NOT been asked yet — ask it now if no higher-priority criterion is uncovered.\n"

    initial_context = ""
    if initial_query:
        initial_context = (
            f"\nUser's original search (DO NOT re-ask anything already covered in it): {initial_query}\n"
        )

    memory_note = ""
    if memory_context:
        facts = [s.get("text", "") for s in memory_context if s.get("text")]
        if facts:
            memory_note = (
                f"\nKNOWN FROM PAST SEARCHES (skip these, user already answered them):\n"
                + "\n".join(f"  - {f}" for f in facts[:6]) + "\n"
            )

    _noun = primary_noun.strip() if primary_noun.strip() else _product_noun(category)
    prompt = f"""Category: {category}
Product: {_noun}

Buying criteria for this product:
{criteria_text}
{initial_context}{memory_note}{budget_note}{brand_note}
Interview so far:
{qa_text}
{coverage_note}

Generate the single best next question."""

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
    if not data.get("is_done") and n >= MIN_QUESTIONS:
        tc = data.get("targets_criterion", "")
        if tc and tc not in ("general", "budget", "brand_preference"):
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
