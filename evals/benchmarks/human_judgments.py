"""
Human alignment benchmarks (Phase 11).

Expert-annotated scenarios define the "correct" ranking and rationale.
ShopSense output is compared against expert judgment to produce the Human Alignment Score.
The closer ShopSense is to expert reasoning, the higher the score.
"""

from __future__ import annotations
from evals.benchmarks.base import HumanJudgment, RubricWeight
from evals.benchmarks.users import _P, _rubric


def _rw(overrides: dict[str, float]) -> list[RubricWeight]:
    return _rubric(overrides)


_PRODUCTS = list(_P.values())


HUMAN_JUDGMENTS: list[HumanJudgment] = [
    HumanJudgment(
        id="hj_daily_commuter",
        name="Expert — Daily NYC Subway Commuter",
        query="best earbuds for noisy subway commute",
        expert_rank_1="PremiumPro A9",
        expert_rank_2="WorkComfort W2",
        expert_rank_3="MidRange M7",
        expert_rationale=(
            "Subway noise peaks at 90-100 dB. Only hybrid ANC earbuds achieve meaningful "
            "attenuation. PremiumPro leads with ANC=9, WorkComfort is a viable second. "
            "Budget earbuds without ANC are disqualified for this use case."
        ),
        products=_PRODUCTS,
        rubric_weights=_rw({
            "noise_cancellation": 10, "battery_life": 9, "comfort": 8,
            "durability": 7, "portability": 7, "price_to_value": 4,
        }),
        key_tradeoffs=[
            "PremiumPro has shorter battery than AthleteFit but vastly better ANC",
            "WorkComfort is better for calls but slightly weaker ANC than PremiumPro",
            "BudgetBuds are unsuitable — no ANC",
        ],
    ),

    HumanJudgment(
        id="hj_marathon_runner",
        name="Expert — Recreational Marathon Runner",
        query="best earbuds for marathon training",
        expert_rank_1="AthleteFit G5",
        expert_rank_2="MidRange M7",
        expert_rank_3="BudgetBuds X3",
        expert_rationale=(
            "Marathon training requires earbuds that stay in during 20+ mile runs, survive sweat, "
            "and last for 3+ hour runs. AthleteFit has the highest security, waterproofing (IP8X), "
            "and battery life. Premium ANC earbuds are a poor fit — they're designed for stillness."
        ),
        products=_PRODUCTS,
        rubric_weights=_rw({
            "comfort": 10, "water_resistance": 9, "battery_life": 9, "durability": 9,
            "portability": 7, "sound_quality": 5, "noise_cancellation": 2, "price_to_value": 5,
        }),
        key_tradeoffs=[
            "AthleteFit's weaker sound quality is acceptable when you're running",
            "PremiumPro has better sound but poor security and waterproofing",
            "BudgetBuds are too fragile for high-sweat daily use",
        ],
    ),

    HumanJudgment(
        id="hj_home_studio",
        name="Expert — Home Studio Music Producer",
        query="best earbuds for music production at home",
        expert_rank_1="AudioPhile H1",
        expert_rank_2="PremiumPro A9",
        expert_rank_3="WorkComfort W2",
        expert_rationale=(
            "Home studio producers need flat frequency response for accurate monitoring. "
            "AudioPhile H1 delivers reference-grade accuracy (sound=9, bass=9 without artificial boost). "
            "PremiumPro is second — great ANC helps with isolation during critical listening. "
            "Budget options introduce coloration that leads to mix translation failures."
        ),
        products=_PRODUCTS,
        rubric_weights=_rw({
            "sound_quality": 10, "bass_response": 9, "comfort": 7,
            "noise_cancellation": 5, "connectivity": 6, "price_to_value": 3,
        }),
        key_tradeoffs=[
            "AudioPhile H1 has shorter battery but that's irrelevant for studio use",
            "PremiumPro's EQ-enhanced bass is a problem for accurate monitoring",
            "GamingEar's gaming-tuned EQ is unsuitable for production",
        ],
    ),

    HumanJudgment(
        id="hj_remote_team_lead",
        name="Expert — Remote Team Lead (5 hours of meetings/day)",
        query="best earbuds for remote team calls all day",
        expert_rank_1="WorkComfort W2",
        expert_rank_2="PremiumPro A9",
        expert_rank_3="MidRange M7",
        expert_rationale=(
            "For 5+ hour call days, three things are non-negotiable: mic clarity (mic=9), "
            "call quality (call=9), and comfort for extended wear (comfort=8). WorkComfort W2 "
            "leads on all three. PremiumPro is second — excellent ANC helps focus between calls, "
            "and its mic is strong. Budget earbuds fail due to poor mic in open-office environments."
        ),
        products=_PRODUCTS,
        rubric_weights=_rw({
            "call_quality": 10, "microphone_quality": 10, "comfort": 9,
            "noise_cancellation": 8, "battery_life": 8, "price_to_value": 4,
        }),
        key_tradeoffs=[
            "WorkComfort edges PremiumPro on mic quality (9 vs 8)",
            "GamingEar has great mic but is uncomfortable for all-day use",
            "BudgetBuds mic is poor in noisy environments",
        ],
    ),

    HumanJudgment(
        id="hj_college_budget",
        name="Expert — College Student, Strict ₹3000 Budget",
        query="best earbuds for college student under ₹3000",
        expert_rank_1="BudgetBuds X3",
        expert_rank_2="CompactBud C3",
        expert_rank_3="MidRange M7",
        expert_rationale=(
            "Under ₹3000 the question is which budget option provides best durability and battery. "
            "BudgetBuds X3 wins on price/value (9) and durability (8). CompactBud is a good second "
            "for students who want portability. MidRange M7 technically exceeds the budget."
        ),
        products=_PRODUCTS,
        rubric_weights=_rw({
            "price_to_value": 10, "durability": 9, "battery_life": 8,
            "sound_quality": 5, "connectivity": 5, "noise_cancellation": 3,
        }),
        key_tradeoffs=[
            "BudgetBuds has no ANC — not ideal for library use but acceptable",
            "CompactBud may not fit all ear sizes",
            "MidRange is genuinely better but too expensive for this budget",
        ],
    ),

    HumanJudgment(
        id="hj_gamer_streamer",
        name="Expert — Gaming Content Creator & Streamer",
        query="best earbuds for PC gaming and streaming",
        expert_rank_1="GamingEar Q4",
        expert_rank_2="WorkComfort W2",
        expert_rank_3="MidRange M7",
        expert_rationale=(
            "Streaming requires two things above all: latency <40ms for sync (gaming_latency=9) "
            "and mic quality that sounds professional on stream (mic=9). GamingEar Q4 is the only "
            "option with both. WorkComfort is second — great mic, acceptable latency. "
            "Audiophile earbuds lack gaming modes and are expensive for live streaming."
        ),
        products=_PRODUCTS,
        rubric_weights=_rw({
            "gaming_latency": 10, "microphone_quality": 10, "sound_quality": 7,
            "comfort": 7, "battery_life": 5, "price_to_value": 5,
        }),
        key_tradeoffs=[
            "GamingEar's 5h battery is a real concern for long streams",
            "AudioPhile has better sound but no gaming mode and poor mic",
            "WorkComfort lacks dedicated gaming mode but has better battery",
        ],
    ),

    HumanJudgment(
        id="hj_long_haul_flight",
        name="Expert — Long-Haul Flight Passenger (14+ hours)",
        query="best earbuds for long flights",
        expert_rank_1="PremiumPro A9",
        expert_rank_2="WorkComfort W2",
        expert_rank_3="AthleteFit G5",
        expert_rationale=(
            "14-hour flights require three things: exceptional ANC to survive engine noise, "
            "enough battery for the full flight, and genuine all-day comfort. PremiumPro leads on "
            "ANC (9). WorkComfort is a strong second with better battery. AthleteFit is third — "
            "excellent battery and comfort but weaker ANC makes it suboptimal for aircraft noise."
        ),
        products=_PRODUCTS,
        rubric_weights=_rw({
            "noise_cancellation": 10, "comfort": 10, "battery_life": 9,
            "sound_quality": 7, "portability": 7, "price_to_value": 3,
        }),
        key_tradeoffs=[
            "AthleteFit has better battery than PremiumPro but weaker ANC",
            "Budget earbuds provide no isolation in aircraft cabin pressure environment",
            "PremiumPro's transparency mode helps at landing and boarding",
        ],
    ),

    HumanJudgment(
        id="hj_yoga_mindfulness",
        name="Expert — Yoga Instructor",
        query="best earbuds for yoga and mindfulness practice",
        expert_rank_1="CompactBud C3",
        expert_rank_2="AthleteFit G5",
        expert_rank_3="MidRange M7",
        expert_rationale=(
            "Yoga requires earbuds that disappear during practice: featherlight, "
            "secure but non-intrusive, and transparent enough to hear the instructor. "
            "CompactBud C3 is the smallest and most comfortable option. AthleteFit is second "
            "for practitioners who also run. Over-ear or premium ANC earbuds are inappropriate."
        ),
        products=_PRODUCTS,
        rubric_weights=_rw({
            "comfort": 10, "portability": 10, "transparency_mode": 7,
            "price_to_value": 7, "battery_life": 6, "noise_cancellation": 2,
        }),
        key_tradeoffs=[
            "CompactBud lacks ANC but ANC is counterproductive in yoga",
            "AthleteFit has better sport credentials but is bulkier",
            "PremiumPro is overkill and uncomfortable for floor exercises",
        ],
    ),

    HumanJudgment(
        id="hj_premium_traveler",
        name="Expert — Business Class Frequent Flyer",
        query="best premium earbuds for frequent business travel",
        expert_rank_1="PremiumPro A9",
        expert_rank_2="AudioPhile H1",
        expert_rank_3="WorkComfort W2",
        expert_rationale=(
            "Business travelers require premium ANC for focus in airports and planes, "
            "plus strong call quality for in-lounge meetings. PremiumPro leads on ANC+calls. "
            "AudioPhile H1 is a personal taste alternative for audiophile travelers. "
            "Price is irrelevant in this segment — only quality counts."
        ),
        products=_PRODUCTS,
        rubric_weights=_rw({
            "noise_cancellation": 9, "call_quality": 9, "sound_quality": 8,
            "comfort": 8, "battery_life": 7, "price_to_value": 1,
        }),
        key_tradeoffs=[
            "AudioPhile trades call quality for sound accuracy",
            "WorkComfort's weaker sound is compensated by best-in-class calls",
            "Budget earbuds are inappropriate for business class",
        ],
    ),

    HumanJudgment(
        id="hj_kids_teenager",
        name="Expert — Teenager (Parents Buying)",
        query="best earbuds for teenager",
        expert_rank_1="BudgetBuds X3",
        expert_rank_2="MidRange M7",
        expert_rank_3="CompactBud C3",
        expert_rationale=(
            "Parents buying for a teenager prioritize: won't cry if they break it (durability+price), "
            "enough sound quality to not embarrass the kid at school, and decent battery. "
            "BudgetBuds wins on price+durability. MidRange M7 is the upgrade option. "
            "AirPods-level products are a theft target and overkill for this age group."
        ),
        products=_PRODUCTS,
        rubric_weights=_rw({
            "price_to_value": 10, "durability": 9, "battery_life": 7,
            "sound_quality": 6, "connectivity": 5, "noise_cancellation": 3,
        }),
        key_tradeoffs=[
            "MidRange is genuinely better but doubles the cost",
            "Premium earbuds are inappropriate — too expensive for a teenager",
            "BudgetBuds' lack of ANC is acceptable for a teenager",
        ],
    ),
]


def all_human_judgments() -> list[HumanJudgment]:
    return HUMAN_JUDGMENTS
