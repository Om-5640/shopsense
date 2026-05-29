"""
Personalization strength benchmarks (Phase 4).

Same query, different user personas → must produce meaningfully different rankings.
A system that gives the same recommendations regardless of persona has ZERO personalization.
"""

from __future__ import annotations
from evals.benchmarks.base import PersonalizationTest, PersonaRubric, RubricWeight
from evals.benchmarks.users import _P, _rubric


def _rw(overrides: dict[str, float]) -> list[RubricWeight]:
    return _rubric(overrides)


_PRODUCTS = list(_P.values())


PERSONALIZATION_TESTS: list[PersonalizationTest] = [
    PersonalizationTest(
        id="pt_best_earbuds",
        name="Best Earbuds — 5 Different Personas",
        description="Same query 'best earbuds' should yield divergent rankings",
        query="best earbuds",
        products=_PRODUCTS,
        min_rank_1_diversity=4,
        personas=[
            PersonaRubric(
                persona_id="gym",
                persona_name="Gym User",
                rubric_weights=_rw({
                    "water_resistance": 9, "comfort": 9, "durability": 9,
                    "battery_life": 8, "sound_quality": 5, "price_to_value": 6,
                }),
                expected_rank_1="AthleteFit G5",
            ),
            PersonaRubric(
                persona_id="traveler",
                persona_name="Frequent Flyer",
                rubric_weights=_rw({
                    "noise_cancellation": 10, "battery_life": 9, "comfort": 8,
                    "sound_quality": 7, "portability": 7, "price_to_value": 3,
                }),
                expected_rank_1="PremiumPro A9",
            ),
            PersonaRubric(
                persona_id="budget",
                persona_name="Budget Buyer",
                rubric_weights=_rw({
                    "price_to_value": 10, "durability": 7, "battery_life": 7,
                    "sound_quality": 5, "noise_cancellation": 2,
                }),
                expected_rank_1="BudgetBuds X3",
            ),
            PersonaRubric(
                persona_id="gamer",
                persona_name="Gamer",
                rubric_weights=_rw({
                    "gaming_latency": 10, "microphone_quality": 9, "sound_quality": 7,
                    "comfort": 7, "price_to_value": 5,
                }),
                expected_rank_1="GamingEar Q4",
            ),
            PersonaRubric(
                persona_id="office",
                persona_name="Office Worker",
                rubric_weights=_rw({
                    "call_quality": 10, "microphone_quality": 9, "noise_cancellation": 8,
                    "comfort": 8, "battery_life": 7, "price_to_value": 4,
                }),
                expected_rank_1="WorkComfort W2",
            ),
        ],
    ),

    PersonalizationTest(
        id="pt_wireless_earbuds",
        name="Wireless Earbuds — 4 Personas",
        description="Different priorities should diverge rankings significantly",
        query="wireless earbuds",
        products=_PRODUCTS,
        min_rank_1_diversity=3,
        personas=[
            PersonaRubric(
                persona_id="audiophile",
                persona_name="Audiophile",
                rubric_weights=_rw({
                    "sound_quality": 10, "bass_response": 9, "comfort": 7,
                    "price_to_value": 3, "noise_cancellation": 4,
                }),
                expected_rank_1="AudioPhile H1",
            ),
            PersonaRubric(
                persona_id="student_budget",
                persona_name="Budget Student",
                rubric_weights=_rw({
                    "price_to_value": 10, "durability": 8, "battery_life": 7,
                    "sound_quality": 5, "noise_cancellation": 3,
                }),
                expected_rank_1="BudgetBuds X3",
            ),
            PersonaRubric(
                persona_id="premium_buyer",
                persona_name="Premium Buyer",
                rubric_weights=_rw({
                    "sound_quality": 9, "noise_cancellation": 9, "comfort": 9,
                    "call_quality": 8, "price_to_value": 1,
                }),
                expected_rank_1="PremiumPro A9",
            ),
            PersonaRubric(
                persona_id="portable",
                persona_name="Minimalist Traveler",
                rubric_weights=_rw({
                    "portability": 10, "comfort": 9, "battery_life": 7,
                    "price_to_value": 7, "durability": 6, "sound_quality": 5,
                }),
                expected_rank_1="CompactBud C3",
            ),
        ],
    ),

    PersonalizationTest(
        id="pt_work_earbuds",
        name="Work Earbuds — 4 Personas",
        description="Even for 'work' query, priorities should diverge",
        query="earbuds for work",
        products=_PRODUCTS,
        min_rank_1_diversity=3,
        personas=[
            PersonaRubric(
                persona_id="call_center",
                persona_name="Call Center Agent",
                rubric_weights=_rw({
                    "call_quality": 10, "microphone_quality": 10, "comfort": 10,
                    "noise_cancellation": 8, "battery_life": 9,
                }),
                expected_rank_1="WorkComfort W2",
            ),
            PersonaRubric(
                persona_id="developer",
                persona_name="Developer (Deep Focus)",
                rubric_weights=_rw({
                    "noise_cancellation": 10, "comfort": 10, "battery_life": 9,
                    "sound_quality": 7, "call_quality": 5,
                }),
                expected_rank_1="PremiumPro A9",
            ),
            PersonaRubric(
                persona_id="startup_budget",
                persona_name="Startup Employee (Budget)",
                rubric_weights=_rw({
                    "price_to_value": 10, "battery_life": 7, "noise_cancellation": 4,
                    "comfort": 5, "durability": 6,
                }),
                expected_rank_1="BudgetBuds X3",
            ),
            PersonaRubric(
                persona_id="creative_director",
                persona_name="Creative Director",
                rubric_weights=_rw({
                    "sound_quality": 10, "bass_response": 9, "comfort": 7,
                    "price_to_value": 3,
                }),
                expected_rank_1="AudioPhile H1",
            ),
        ],
    ),

    PersonalizationTest(
        id="pt_commute_earbuds",
        name="Commute Earbuds — 4 Personas",
        description="Commute query should diverge based on transport type and priorities",
        query="earbuds for daily commute",
        products=_PRODUCTS,
        min_rank_1_diversity=3,
        personas=[
            PersonaRubric(
                persona_id="subway_commuter",
                persona_name="Subway Commuter",
                rubric_weights=_rw({
                    "noise_cancellation": 10, "battery_life": 7, "comfort": 7,
                    "sound_quality": 6, "price_to_value": 3,
                }),
                expected_rank_1="PremiumPro A9",
            ),
            PersonaRubric(
                persona_id="cyclist_commuter",
                persona_name="Cycling Commuter",
                rubric_weights=_rw({
                    "transparency_mode": 10, "comfort": 9, "water_resistance": 8,
                    "durability": 8, "battery_life": 7, "price_to_value": 6,
                }),
                expected_rank_1="AthleteFit G5",
            ),
            PersonaRubric(
                persona_id="budget_commuter",
                persona_name="Budget Commuter",
                rubric_weights=_rw({
                    "price_to_value": 10, "durability": 8, "battery_life": 7,
                    "noise_cancellation": 3, "portability": 6,
                }),
                expected_rank_1="BudgetBuds X3",
            ),
            PersonaRubric(
                persona_id="exec_commuter",
                persona_name="Executive Commuter",
                rubric_weights=_rw({
                    "noise_cancellation": 9, "call_quality": 9, "sound_quality": 8,
                    "comfort": 8, "battery_life": 7, "price_to_value": 1,
                }),
                expected_rank_1="PremiumPro A9",
            ),
        ],
    ),

    PersonalizationTest(
        id="pt_sport_earbuds",
        name="Sport Earbuds — 4 Personas",
        description="Sport query should diverge based on specific sport and budget",
        query="earbuds for sport",
        products=_PRODUCTS,
        min_rank_1_diversity=3,
        personas=[
            PersonaRubric(
                persona_id="swimmer",
                persona_name="Swimmer",
                rubric_weights=_rw({
                    "water_resistance": 10, "durability": 9, "comfort": 9,
                    "battery_life": 7, "price_to_value": 6,
                }),
                expected_rank_1="AthleteFit G5",
            ),
            PersonaRubric(
                persona_id="budget_gym",
                persona_name="Budget Gym User",
                rubric_weights=_rw({
                    "price_to_value": 9, "water_resistance": 7, "durability": 8,
                    "comfort": 7, "battery_life": 7,
                }),
                expected_rank_1="BudgetBuds X3",
            ),
            PersonaRubric(
                persona_id="gamer_streamer",
                persona_name="Esports Player",
                rubric_weights=_rw({
                    "gaming_latency": 10, "microphone_quality": 9, "comfort": 8,
                    "sound_quality": 7, "price_to_value": 5,
                }),
                expected_rank_1="GamingEar Q4",
            ),
            PersonaRubric(
                persona_id="yoga",
                persona_name="Yoga Practitioner",
                rubric_weights=_rw({
                    "comfort": 10, "portability": 9, "transparency_mode": 8,
                    "price_to_value": 7, "noise_cancellation": 2,
                }),
                expected_rank_1="CompactBud C3",
            ),
        ],
    ),
]


def all_personalization_tests() -> list[PersonalizationTest]:
    return PERSONALIZATION_TESTS
