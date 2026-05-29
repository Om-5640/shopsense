"""
100+ offline benchmark scenarios for ShopSense.

Every scenario is deterministic: given these rubric weights and product scores,
exactly one ranking is correct. No LLM calls needed.

Product pool (earbuds/headphones — primary ShopSense category):

  BudgetBuds X3    – cheap, decent, no ANC, tough
  MidRange M7      – balanced all-rounder
  PremiumPro A9    – expensive, best ANC, best sound
  AthleteFit G5    – sport-focused, waterproof, secure fit, long battery
  GamingEar Q4     – great mic, lowest latency, bass-heavy
  WorkComfort W2   – ANC + best mic/call quality, office-optimised
  AudioPhile H1    – reference-grade sound + bass, no ANC
  CompactBud C3    – smallest, most portable, lightweight

Criteria (15):
  sound_quality · bass_response · noise_cancellation · transparency_mode
  battery_life · comfort · durability · water_resistance
  microphone_quality · call_quality · price_to_value
  gaming_latency · portability · connectivity · ecosystem_integration
"""

from __future__ import annotations
from evals.benchmarks.base import (
    OfflineScenario, ProductProfile, RubricWeight,
)

# ── Product definitions ────────────────────────────────────────────────────────

_P = {
    "BudgetBuds X3": ProductProfile(
        name="BudgetBuds X3",
        criterion_scores={
            "sound_quality": 5, "bass_response": 6, "noise_cancellation": 2,
            "transparency_mode": 1, "battery_life": 7, "comfort": 6,
            "durability": 8, "water_resistance": 3, "microphone_quality": 4,
            "call_quality": 4, "price_to_value": 9, "gaming_latency": 5,
            "portability": 7, "connectivity": 6, "ecosystem_integration": 2,
        },
        signal_strength="moderate", mention_count=35,
        positive_mentions=22, negative_mentions=13,
        praise=["unbeatable price", "tough build"],
        complaints=[{"text": "no ANC", "confidence": "high"}, {"text": "average sound", "confidence": "medium"}],
    ),
    "MidRange M7": ProductProfile(
        name="MidRange M7",
        criterion_scores={
            "sound_quality": 7, "bass_response": 7, "noise_cancellation": 6,
            "transparency_mode": 5, "battery_life": 8, "comfort": 7,
            "durability": 7, "water_resistance": 6, "microphone_quality": 7,
            "call_quality": 7, "price_to_value": 6, "gaming_latency": 6,
            "portability": 6, "connectivity": 8, "ecosystem_integration": 5,
        },
        signal_strength="strong", mention_count=62,
        positive_mentions=44, negative_mentions=18,
        praise=["great all-rounder", "solid battery", "good calls"],
        complaints=[{"text": "nothing exceptional", "confidence": "low"}],
    ),
    "PremiumPro A9": ProductProfile(
        name="PremiumPro A9",
        criterion_scores={
            "sound_quality": 9, "bass_response": 7, "noise_cancellation": 9,
            "transparency_mode": 8, "battery_life": 6, "comfort": 8,
            "durability": 7, "water_resistance": 5, "microphone_quality": 8,
            "call_quality": 8, "price_to_value": 3, "gaming_latency": 5,
            "portability": 5, "connectivity": 9, "ecosystem_integration": 9,
        },
        signal_strength="strong", mention_count=88,
        positive_mentions=70, negative_mentions=18,
        praise=["best-in-class ANC", "premium sound", "seamless pairing"],
        complaints=[{"text": "very expensive", "confidence": "high"}, {"text": "short battery", "confidence": "medium"}],
    ),
    "AthleteFit G5": ProductProfile(
        name="AthleteFit G5",
        criterion_scores={
            "sound_quality": 6, "bass_response": 5, "noise_cancellation": 3,
            "transparency_mode": 2, "battery_life": 9, "comfort": 9,
            "durability": 9, "water_resistance": 9, "microphone_quality": 5,
            "call_quality": 5, "price_to_value": 4, "gaming_latency": 6,
            "portability": 8, "connectivity": 7, "ecosystem_integration": 3,
        },
        signal_strength="strong", mention_count=54,
        positive_mentions=46, negative_mentions=8,
        praise=["never falls out", "IPX8 waterproof", "incredible battery", "all-day comfort"],
        complaints=[{"text": "mediocre ANC", "confidence": "high"}, {"text": "pricey for sport", "confidence": "medium"}],
    ),
    "GamingEar Q4": ProductProfile(
        name="GamingEar Q4",
        criterion_scores={
            "sound_quality": 7, "bass_response": 8, "noise_cancellation": 4,
            "transparency_mode": 3, "battery_life": 5, "comfort": 8,
            "durability": 6, "water_resistance": 2, "microphone_quality": 9,
            "call_quality": 8, "price_to_value": 6, "gaming_latency": 9,
            "portability": 6, "connectivity": 8, "ecosystem_integration": 4,
        },
        signal_strength="moderate", mention_count=41,
        positive_mentions=30, negative_mentions=11,
        praise=["near-zero latency", "crystal-clear mic", "bass punch"],
        complaints=[{"text": "short 5h battery", "confidence": "high"}, {"text": "not waterproof", "confidence": "high"}],
    ),
    "WorkComfort W2": ProductProfile(
        name="WorkComfort W2",
        criterion_scores={
            "sound_quality": 7, "bass_response": 5, "noise_cancellation": 8,
            "transparency_mode": 7, "battery_life": 7, "comfort": 8,
            "durability": 7, "water_resistance": 4, "microphone_quality": 9,
            "call_quality": 9, "price_to_value": 5, "gaming_latency": 4,
            "portability": 5, "connectivity": 8, "ecosystem_integration": 6,
        },
        signal_strength="strong", mention_count=49,
        positive_mentions=40, negative_mentions=9,
        praise=["call quality praised by teams", "solid ANC", "comfortable for long days"],
        complaints=[{"text": "bulky case", "confidence": "medium"}],
    ),
    "AudioPhile H1": ProductProfile(
        name="AudioPhile H1",
        criterion_scores={
            "sound_quality": 9, "bass_response": 9, "noise_cancellation": 5,
            "transparency_mode": 6, "battery_life": 5, "comfort": 7,
            "durability": 8, "water_resistance": 3, "microphone_quality": 7,
            "call_quality": 7, "price_to_value": 4, "gaming_latency": 4,
            "portability": 7, "connectivity": 7, "ecosystem_integration": 5,
        },
        signal_strength="moderate", mention_count=28,
        positive_mentions=24, negative_mentions=4,
        praise=["audiophile-grade sound", "reference bass", "studio accuracy"],
        complaints=[{"text": "short battery", "confidence": "high"}, {"text": "niche appeal", "confidence": "medium"}],
    ),
    "CompactBud C3": ProductProfile(
        name="CompactBud C3",
        criterion_scores={
            "sound_quality": 6, "bass_response": 5, "noise_cancellation": 3,
            "transparency_mode": 2, "battery_life": 6, "comfort": 8,
            "durability": 7, "water_resistance": 5, "microphone_quality": 5,
            "call_quality": 5, "price_to_value": 8, "gaming_latency": 5,
            "portability": 9, "connectivity": 7, "ecosystem_integration": 4,
        },
        signal_strength="moderate", mention_count=19,
        positive_mentions=14, negative_mentions=5,
        praise=["featherlight", "tiny case", "comfortable for small ears"],
        complaints=[{"text": "lacks bass", "confidence": "medium"}, {"text": "weak mic", "confidence": "medium"}],
    ),
}

_ALL = list(_P.values())


# ── Helpers ────────────────────────────────────────────────────────────────────

def _rubric(overrides: dict[str, float], base_weight: float = 0.0) -> list[RubricWeight]:
    """Build a rubric using provided weights; unspecified criteria default to base_weight (0 = only specified criteria count)."""
    criteria = [
        ("sound_quality", "Sound Quality"),
        ("bass_response", "Bass Response"),
        ("noise_cancellation", "Noise Cancellation"),
        ("transparency_mode", "Transparency Mode"),
        ("battery_life", "Battery Life"),
        ("comfort", "Comfort & Fit"),
        ("durability", "Durability"),
        ("water_resistance", "Water Resistance"),
        ("microphone_quality", "Microphone Quality"),
        ("call_quality", "Call Quality"),
        ("price_to_value", "Price to Value"),
        ("gaming_latency", "Gaming Latency"),
        ("portability", "Portability"),
        ("connectivity", "Bluetooth Connectivity"),
        ("ecosystem_integration", "Ecosystem Integration"),
    ]
    return [RubricWeight(k, label, overrides.get(k, base_weight)) for k, label in criteria]


def _s(
    id_: str,
    name: str,
    tags: list[str],
    rubric_overrides: dict[str, float],
    expected_rank_1: str,
    desc: str = "",
    not_rank_1: list[str] | None = None,
    top2: list[str] | None = None,
    products: list | None = None,
    intent: dict | None = None,
    base_weight: float = 0.0,
) -> OfflineScenario:
    return OfflineScenario(
        id=id_,
        name=name,
        description=desc or name,
        tags=tags,
        products=products or _ALL,
        rubric_weights=_rubric(rubric_overrides, base_weight),
        expected_rank_1=expected_rank_1,
        expected_rank_1_not=not_rank_1 or [],
        expected_top_2=top2 or [],
        intent=intent or {},
    )


# ── STUDENTS (15) ─────────────────────────────────────────────────────────────

STUDENT_SCENARIOS: list[OfflineScenario] = [
    _s("student_budget_india", "Student — Budget India ₹3000",
       ["student", "budget", "india"],
       {"price_to_value": 10, "durability": 7, "battery_life": 7, "sound_quality": 5,
        "noise_cancellation": 2, "call_quality": 4},
       "BudgetBuds X3",
       "Indian student on tight budget — value for money trumps everything"),

    _s("student_budget_us", "Student — Budget US $30",
       ["student", "budget", "us"],
       {"price_to_value": 10, "durability": 8, "battery_life": 6, "sound_quality": 5,
        "noise_cancellation": 2, "comfort": 5},
       "BudgetBuds X3",
       "US student on $30 budget"),

    _s("student_library", "Student — Library Study Sessions",
       ["student", "anc", "study"],
       {"noise_cancellation": 10, "battery_life": 8, "comfort": 8, "sound_quality": 7,
        "price_to_value": 4},
       "PremiumPro A9",
       "Long library sessions — ANC + battery + comfort critical"),

    _s("student_commute_daily", "Student — Daily Bus Commute",
       ["student", "commute", "durability"],
       {"durability": 9, "battery_life": 9, "water_resistance": 7, "portability": 8,
        "price_to_value": 6, "comfort": 7},
       "AthleteFit G5",
       "Dropped frequently, long commutes — rugged + long battery wins"),

    _s("student_dorm", "Student — Shared Dorm Room",
       ["student", "anc", "social"],
       {"noise_cancellation": 9, "comfort": 8, "battery_life": 8, "sound_quality": 7,
        "price_to_value": 5},
       "PremiumPro A9",
       "Needs to block out loud roommates while studying"),

    _s("student_gaming_study", "Student — Gaming & Studying",
       ["student", "gaming", "dual-use"],
       {"gaming_latency": 8, "microphone_quality": 8, "sound_quality": 7,
        "battery_life": 6, "price_to_value": 7, "noise_cancellation": 4},
       "GamingEar Q4",
       "Switches between Zoom lectures and evening gaming"),

    _s("student_remote_class", "Student — Remote Classes + Zoom",
       ["student", "mic", "calls"],
       {"microphone_quality": 9, "call_quality": 9, "noise_cancellation": 7,
        "battery_life": 8, "comfort": 7, "price_to_value": 6},
       "WorkComfort W2",
       "All-day online lectures — mic quality critical"),

    _s("student_iphone", "Student — iPhone Ecosystem",
       ["student", "apple", "ecosystem"],
       {"ecosystem_integration": 9, "sound_quality": 7, "noise_cancellation": 7,
        "comfort": 7, "battery_life": 6, "price_to_value": 4},
       "PremiumPro A9",
       "iPhone user wanting seamless Apple integration"),

    _s("student_athlete", "Student — Student Athlete",
       ["student", "sport", "gym"],
       {"water_resistance": 9, "durability": 9, "comfort": 9, "battery_life": 8,
        "price_to_value": 6, "sound_quality": 5},
       "AthleteFit G5",
       "Daily sport + studying — secure fit and durability non-negotiable"),

    _s("student_audiophile", "Student — Music Student / Audiophile",
       ["student", "audiophile", "music"],
       {"sound_quality": 10, "bass_response": 9, "comfort": 7, "price_to_value": 6},
       "AudioPhile H1",
       "Music major — accuracy and soundstage critical"),

    _s("student_call_center_parttime", "Student — Part-Time Call Center Job",
       ["student", "mic", "calls", "work"],
       {"call_quality": 10, "microphone_quality": 10, "comfort": 9,
        "battery_life": 8, "noise_cancellation": 7, "price_to_value": 5},
       "WorkComfort W2",
       "Works 6-hour call shifts — mic + comfort is everything"),

    _s("student_international", "Student — International / Frequent Flyer",
       ["student", "travel", "anc"],
       {"noise_cancellation": 9, "battery_life": 9, "portability": 8, "comfort": 8,
        "sound_quality": 6, "price_to_value": 5},
       "PremiumPro A9",
       "Monthly flights home — ANC, battery, portability"),

    _s("student_all_day", "Student — All-Day Wear (12 hours)",
       ["student", "comfort", "long-wear"],
       {"comfort": 10, "battery_life": 10, "water_resistance": 6, "durability": 8,
        "portability": 7, "price_to_value": 5},
       "AthleteFit G5",
       "12-hour study marathons — comfort and battery trump everything"),

    _s("student_first_earbuds", "Student — First Wireless Earbuds",
       ["student", "budget", "first-purchase"],
       {"price_to_value": 10, "durability": 5, "battery_life": 5,
        "connectivity": 5, "comfort": 4, "sound_quality": 3},
       "BudgetBuds X3",
       "Never owned wireless earbuds — wants value without risk"),

    _s("student_online_teacher", "Student — Tutors Online Part-Time",
       ["student", "mic", "calls", "teaching"],
       {"microphone_quality": 10, "call_quality": 9, "noise_cancellation": 8,
        "battery_life": 7, "comfort": 7, "price_to_value": 6},
       "WorkComfort W2",
       "Online tutoring sessions — mic clarity is critical"),
]

# ── GYM / SPORTS (12) ─────────────────────────────────────────────────────────

GYM_SCENARIOS: list[OfflineScenario] = [
    _s("gym_runner_marathon", "Gym — Marathon Runner",
       ["gym", "running", "sport"],
       {"water_resistance": 9, "comfort": 10, "battery_life": 9, "durability": 9,
        "portability": 8, "sound_quality": 5, "noise_cancellation": 2, "price_to_value": 6},
       "AthleteFit G5",
       "50+ km/week runner — earbuds must never fall and last hours"),

    _s("gym_weightlifter", "Gym — Weightlifter",
       ["gym", "weightlifting", "sport"],
       {"durability": 9, "sound_quality": 6, "bass_response": 8, "comfort": 8,
        "battery_life": 8, "water_resistance": 7, "price_to_value": 6},
       "AthleteFit G5",
       "Heavy sessions, drops equipment — durability + motivating bass"),

    _s("gym_hiit", "Gym — HIIT & Interval Training",
       ["gym", "hiit", "sport"],
       {"comfort": 10, "water_resistance": 9, "durability": 9, "battery_life": 7,
        "sound_quality": 5, "bass_response": 7, "price_to_value": 5},
       "AthleteFit G5",
       "Intense intervals — must not move a millimeter"),

    _s("gym_outdoor_trail", "Gym — Trail Runner / Outdoor",
       ["gym", "outdoor", "trail"],
       {"water_resistance": 10, "durability": 10, "battery_life": 9, "comfort": 9,
        "transparency_mode": 6, "sound_quality": 5, "price_to_value": 5},
       "AthleteFit G5",
       "Rain + mud + long distances — ruggedness is critical"),

    _s("gym_swimmer", "Gym — Lap Swimmer",
       ["gym", "swimming", "waterproof"],
       {"water_resistance": 10, "durability": 9, "comfort": 9, "battery_life": 7,
        "sound_quality": 5, "price_to_value": 6},
       "AthleteFit G5",
       "Lap swimming — IPX8 waterproof is mandatory"),

    _s("gym_cyclist", "Gym — Road Cyclist",
       ["gym", "cycling", "awareness"],
       {"transparency_mode": 10, "sound_quality": 6, "comfort": 7,
        "battery_life": 6, "portability": 5},
       "PremiumPro A9",
       "Road cycling — must hear traffic, premium transparency mode is essential"),

    _s("gym_yoga", "Gym — Yoga Practitioner",
       ["gym", "yoga", "comfort"],
       {"comfort": 10, "portability": 10, "sound_quality": 5, "price_to_value": 8},
       "CompactBud C3",
       "Yoga — tiny, featherlight, comfortable"),

    _s("gym_crossfit", "Gym — CrossFit Athlete",
       ["gym", "crossfit", "durability"],
       {"durability": 10, "water_resistance": 9, "comfort": 9, "battery_life": 8,
        "bass_response": 7, "price_to_value": 5},
       "AthleteFit G5",
       "CrossFit throws equipment — near-indestructible earbuds"),

    _s("gym_casual_3x_week", "Gym — Casual 3x/Week",
       ["gym", "casual", "balanced"],
       {"sound_quality": 7, "battery_life": 8, "comfort": 8,
        "price_to_value": 8, "connectivity": 7},
       "MidRange M7",
       "Moderate gym-goer — balance of all attributes, decent price"),

    _s("gym_ultra_distance", "Gym — Ultra-Distance Athlete",
       ["gym", "endurance", "battery"],
       {"battery_life": 10, "comfort": 10, "durability": 9, "water_resistance": 8,
        "portability": 7, "sound_quality": 4, "price_to_value": 5},
       "AthleteFit G5",
       "8+ hour endurance events — battery life is everything"),

    _s("gym_beginner", "Gym — Gym Beginner (First Pair)",
       ["gym", "beginner", "budget"],
       {"price_to_value": 10, "durability": 5, "battery_life": 5, "sound_quality": 3},
       "BudgetBuds X3",
       "Just started gym — wants something cheap to try"),

    _s("gym_competitive_sport", "Gym — Competitive Athlete",
       ["gym", "competitive", "performance"],
       {"comfort": 10, "water_resistance": 10, "durability": 10, "battery_life": 9,
        "sound_quality": 5, "price_to_value": 4},
       "AthleteFit G5",
       "Pro-level performance — comfort, security, endurance"),
]

# ── TRAVELERS (10) ────────────────────────────────────────────────────────────

TRAVELER_SCENARIOS: list[OfflineScenario] = [
    _s("traveler_frequent_flyer", "Traveler — Frequent Flyer (Weekly Flights)",
       ["traveler", "anc", "premium"],
       {"noise_cancellation": 10, "battery_life": 9, "comfort": 9, "sound_quality": 7,
        "portability": 7, "price_to_value": 3},
       "PremiumPro A9",
       "Weekly flights — premium ANC and comfort at any price"),

    _s("traveler_budget_backpacker", "Traveler — Budget Backpacker",
       ["traveler", "budget", "durability"],
       {"price_to_value": 10, "durability": 6, "battery_life": 5, "portability": 5},
       "BudgetBuds X3",
       "Backpacking on a shoestring — value + durability + light"),

    _s("traveler_business", "Traveler — Business Executive",
       ["traveler", "business", "calls"],
       {"call_quality": 9, "microphone_quality": 9, "noise_cancellation": 8,
        "comfort": 8, "battery_life": 7, "price_to_value": 4},
       "WorkComfort W2",
       "Airport calls + flight focus — best mic and call quality"),

    _s("traveler_road_trip", "Traveler — Road Trip",
       ["traveler", "road", "battery"],
       {"battery_life": 10, "comfort": 9, "call_quality": 7, "sound_quality": 7,
        "connectivity": 7, "price_to_value": 6, "water_resistance": 5},
       "AthleteFit G5",
       "12-hour drives — battery and comfort critical"),

    _s("traveler_long_haul", "Traveler — Long-Haul Flights (15+ hours)",
       ["traveler", "anc", "comfort", "long-wear"],
       {"noise_cancellation": 10, "comfort": 10, "battery_life": 9,
        "transparency_mode": 6, "sound_quality": 7, "price_to_value": 3},
       "PremiumPro A9",
       "15+ hour flights — best possible ANC + comfort"),

    _s("traveler_adventure", "Traveler — Adventure / Extreme Sports",
       ["traveler", "outdoor", "rugged"],
       {"water_resistance": 10, "durability": 10, "battery_life": 8, "comfort": 8,
        "price_to_value": 5},
       "AthleteFit G5",
       "Kayaking, climbing, surfing — truly rugged earbuds"),

    _s("traveler_international", "Traveler — International Multi-Country",
       ["traveler", "reliability", "battery"],
       {"battery_life": 9, "connectivity": 9, "durability": 7,
        "price_to_value": 7, "sound_quality": 6},
       "MidRange M7",
       "Crossing multiple countries — reliable, versatile, good value"),

    _s("traveler_metro_commuter", "Traveler — Urban Metro Commuter",
       ["traveler", "commute", "anc"],
       {"noise_cancellation": 9, "battery_life": 8, "portability": 8,
        "price_to_value": 8, "connectivity": 8, "sound_quality": 6},
       "MidRange M7",
       "Daily metro commute — balanced ANC + price + connectivity"),

    _s("traveler_nature_hiker", "Traveler — Nature Hiker",
       ["traveler", "outdoor", "awareness"],
       {"water_resistance": 9, "battery_life": 9, "durability": 9, "transparency_mode": 7,
        "comfort": 8, "portability": 7, "price_to_value": 5},
       "AthleteFit G5",
       "Day hikes — transparency mode for trail safety"),

    _s("traveler_minimalist", "Traveler — Ultra-Minimalist Packer",
       ["traveler", "portable", "compact"],
       {"portability": 10, "comfort": 9, "price_to_value": 7, "battery_life": 6},
       "CompactBud C3",
       "One-bag traveler — smallest possible earbuds only"),
]

# ── OFFICE WORKERS (10) ───────────────────────────────────────────────────────

OFFICE_SCENARIOS: list[OfflineScenario] = [
    _s("office_open_floor", "Office — Open-Plan Office Floor",
       ["office", "anc", "focus"],
       {"noise_cancellation": 10, "comfort": 9, "call_quality": 8, "microphone_quality": 8,
        "battery_life": 8, "sound_quality": 6, "price_to_value": 4},
       "WorkComfort W2",
       "Noisy open floor — needs strong ANC for focus"),

    _s("office_home_wfh", "Office — Full-Time WFH",
       ["office", "wfh", "calls"],
       {"call_quality": 10, "microphone_quality": 10, "comfort": 9, "noise_cancellation": 8,
        "battery_life": 8, "transparency_mode": 6, "price_to_value": 5},
       "WorkComfort W2",
       "All-day calls from home — best mic + call quality"),

    _s("office_meetings_heavy", "Office — Meetings-Heavy Role",
       ["office", "calls", "mic"],
       {"call_quality": 10, "microphone_quality": 10, "comfort": 9, "noise_cancellation": 8,
        "battery_life": 7, "price_to_value": 4},
       "WorkComfort W2",
       "6+ hours/day of video calls — mic and call clarity first"),

    _s("office_deep_focus", "Office — Deep Focus Developer",
       ["office", "anc", "focus"],
       {"noise_cancellation": 10, "comfort": 10, "battery_life": 9, "sound_quality": 7,
        "transparency_mode": 5, "price_to_value": 4},
       "PremiumPro A9",
       "Engineers who need to disappear for hours — best ANC"),

    _s("office_hybrid_worker", "Office — Hybrid Worker (Home + Office)",
       ["office", "hybrid", "versatile"],
       {"battery_life": 9, "call_quality": 8, "microphone_quality": 8,
        "noise_cancellation": 8, "comfort": 8, "portability": 7, "price_to_value": 5},
       "WorkComfort W2",
       "Home 3 days, office 2 days — versatile all-day earbuds"),

    _s("office_executive", "Office — Executive / Manager",
       ["office", "premium", "calls"],
       {"call_quality": 9, "microphone_quality": 9, "noise_cancellation": 8,
        "sound_quality": 8, "comfort": 8, "ecosystem_integration": 7, "price_to_value": 2},
       "PremiumPro A9",
       "Senior exec — premium quality + ecosystem integration"),

    _s("office_creative", "Office — Creative Director",
       ["office", "creative", "sound"],
       {"sound_quality": 9, "bass_response": 9, "comfort": 8, "price_to_value": 4},
       "AudioPhile H1",
       "Music + creative work — sound quality drives output"),

    _s("office_call_center_8h", "Office — Call Center (8-Hour Shifts)",
       ["office", "calls", "comfort", "mic"],
       {"call_quality": 10, "microphone_quality": 10, "comfort": 10, "noise_cancellation": 8,
        "battery_life": 9, "price_to_value": 5},
       "WorkComfort W2",
       "Non-stop calls for 8 hours — comfort + mic are survival"),

    _s("office_remote_global_team", "Office — Global Remote Team",
       ["office", "calls", "clarity"],
       {"call_quality": 10, "microphone_quality": 10, "noise_cancellation": 9,
        "battery_life": 8, "comfort": 7, "connectivity": 8, "price_to_value": 4},
       "WorkComfort W2",
       "International calls across 5 time zones — perfect mic clarity"),

    _s("office_standing_desk", "Office — Active Worker / Standing Desk",
       ["office", "comfort", "active"],
       {"call_quality": 8, "noise_cancellation": 8, "comfort": 9,
        "battery_life": 8, "connectivity": 8, "price_to_value": 5},
       "WorkComfort W2",
       "Constantly moving — needs solid ANC, call quality, and comfort"),
]

# ── AUDIOPHILES (8) ───────────────────────────────────────────────────────────

AUDIOPHILE_SCENARIOS: list[OfflineScenario] = [
    _s("audiophile_studio", "Audiophile — Music Producer/Mixer",
       ["audiophile", "studio", "accuracy"],
       {"sound_quality": 10, "bass_response": 9, "comfort": 7, "price_to_value": 3},
       "AudioPhile H1",
       "Reference-grade accuracy for mixing and producing"),

    _s("audiophile_classical", "Audiophile — Classical Music Listener",
       ["audiophile", "classical", "detail"],
       {"sound_quality": 10, "bass_response": 6, "comfort": 8, "price_to_value": 3,
        "gaming_latency": 1},
       "AudioPhile H1",
       "Classical listener prioritises midrange and spatial accuracy"),

    _s("audiophile_bass_head", "Audiophile — Bass-Head / EDM Fan",
       ["audiophile", "bass", "edm"],
       {"bass_response": 10, "sound_quality": 8, "comfort": 7,
        "price_to_value": 5, "battery_life": 5},
       "AudioPhile H1",
       "EDM and hip-hop — wants skull-rattling bass"),

    _s("audiophile_hip_hop", "Audiophile — Hip-Hop & R&B Fan",
       ["audiophile", "bass", "hip-hop"],
       {"bass_response": 10, "sound_quality": 8, "comfort": 7, "price_to_value": 5},
       "AudioPhile H1",
       "Hip-hop listener — best bass punch and soundstage"),

    _s("audiophile_jazz", "Audiophile — Jazz Listener",
       ["audiophile", "jazz", "midrange"],
       {"sound_quality": 10, "bass_response": 6, "comfort": 8, "price_to_value": 4},
       "AudioPhile H1",
       "Jazz — midrange accuracy and warmth over bass boost"),

    _s("audiophile_gaming", "Audiophile — Audiophile Gamer",
       ["audiophile", "gaming", "dual-use"],
       {"sound_quality": 9, "gaming_latency": 8, "bass_response": 8, "microphone_quality": 7,
        "comfort": 7, "price_to_value": 4},
       "GamingEar Q4",
       "Gaming + music — latency + sound quality both matter"),

    _s("audiophile_budget", "Audiophile — Budget Audiophile",
       ["audiophile", "budget", "value"],
       {"sound_quality": 8, "price_to_value": 8, "battery_life": 7,
        "bass_response": 5, "comfort": 5},
       "MidRange M7",
       "Wants audiophile quality without the price — best sound per dollar"),

    _s("audiophile_reference", "Audiophile — Professional Reference Monitoring",
       ["audiophile", "reference", "pro"],
       {"sound_quality": 10, "bass_response": 9, "price_to_value": 2, "comfort": 8},
       "AudioPhile H1",
       "Professional mastering reference — accuracy over everything"),
]

# ── BUDGET BUYERS (10) ────────────────────────────────────────────────────────

BUDGET_SCENARIOS: list[OfflineScenario] = [
    _s("budget_absolute_min", "Budget — Absolute Minimum (under ₹2000 / $20)",
       ["budget", "minimum"],
       {"price_to_value": 10, "durability": 7, "battery_life": 6,
        "sound_quality": 4, "connectivity": 5},
       "BudgetBuds X3",
       "Ultra-tight budget — only price matters"),

    _s("budget_india_3k5k", "Budget — India ₹3000-5000",
       ["budget", "india", "mid-low"],
       {"price_to_value": 9, "durability": 7, "battery_life": 7, "connectivity": 5},
       "BudgetBuds X3",
       "Indian mid-low budget — value and reliability"),

    _s("budget_india_6k10k", "Budget — India ₹6000-10000",
       ["budget", "india", "mid"],
       {"price_to_value": 7, "sound_quality": 7, "battery_life": 9, "connectivity": 7},
       "MidRange M7",
       "Indian mid budget — balanced value, some features"),

    _s("budget_us_30", "Budget — US $30",
       ["budget", "us"],
       {"price_to_value": 10, "durability": 5, "battery_life": 5, "sound_quality": 3},
       "BudgetBuds X3",
       "$30 US budget — cheapest that works"),

    _s("budget_us_50", "Budget — US $50",
       ["budget", "us", "mid-low"],
       {"price_to_value": 8, "sound_quality": 7, "battery_life": 8, "comfort": 6,
        "connectivity": 7},
       "MidRange M7",
       "$50 US budget — step up in quality"),

    _s("budget_gift_uncertain", "Budget — Gift (Unsure of Preferences)",
       ["budget", "gift"],
       {"price_to_value": 7, "sound_quality": 7, "battery_life": 8, "comfort": 7,
        "connectivity": 7},
       "MidRange M7",
       "Gifting to someone — safe balanced choice"),

    _s("budget_teenager", "Budget — Teenager (Parents Buying)",
       ["budget", "teenager"],
       {"price_to_value": 10, "durability": 5, "battery_life": 5, "sound_quality": 4},
       "BudgetBuds X3",
       "Parents buying for teen — cheap + durable"),

    _s("budget_replace_broken", "Budget — Replacing Broken Pair Quickly",
       ["budget", "replacement"],
       {"price_to_value": 10, "battery_life": 7, "durability": 8, "connectivity": 7,
        "sound_quality": 5},
       "BudgetBuds X3",
       "Urgent replacement — cheap, works, ships fast"),

    _s("budget_multiple_family", "Budget — Buying Multiple for Family",
       ["budget", "family", "multiple"],
       {"price_to_value": 10, "durability": 8, "battery_life": 7, "sound_quality": 5,
        "comfort": 6},
       "BudgetBuds X3",
       "Buying 4+ pairs for family — unit price dominates"),

    _s("budget_student_loan", "Budget — Student Loan Stress Budget",
       ["budget", "student", "extreme"],
       {"price_to_value": 10, "durability": 9, "battery_life": 6,
        "sound_quality": 4},
       "BudgetBuds X3",
       "Broke student — only option is cheapest possible"),
]

# ── PREMIUM BUYERS (7) ────────────────────────────────────────────────────────

PREMIUM_SCENARIOS: list[OfflineScenario] = [
    _s("premium_flagship", "Premium — Flagship Best-in-Class",
       ["premium", "flagship"],
       {"sound_quality": 10, "noise_cancellation": 10, "comfort": 9, "call_quality": 9,
        "microphone_quality": 9, "battery_life": 7, "price_to_value": 1},
       "PremiumPro A9",
       "No budget limit — absolute best product"),

    _s("premium_no_compromise", "Premium — No-Compromise Buyer",
       ["premium", "no-compromise"],
       {"sound_quality": 9, "noise_cancellation": 9, "comfort": 9, "durability": 8,
        "call_quality": 8, "battery_life": 7, "price_to_value": 1},
       "PremiumPro A9",
       "Will spend whatever it takes for quality"),

    _s("premium_executive_gift", "Premium — Premium Gift for Executive",
       ["premium", "gift", "executive"],
       {"sound_quality": 9, "noise_cancellation": 9, "call_quality": 9,
        "ecosystem_integration": 8, "comfort": 8, "price_to_value": 1},
       "PremiumPro A9",
       "Premium gift — impressive, not asking about price"),

    _s("premium_audiophile_gift", "Premium — High-End Gift for Music Lover",
       ["premium", "audiophile", "gift"],
       {"sound_quality": 10, "bass_response": 9, "comfort": 8, "price_to_value": 1},
       "AudioPhile H1",
       "Gift for audiophile — sound quality above everything"),

    _s("premium_apple", "Premium — Premium Apple Ecosystem",
       ["premium", "apple", "ecosystem"],
       {"ecosystem_integration": 10, "sound_quality": 9, "noise_cancellation": 9,
        "call_quality": 8, "comfort": 8, "price_to_value": 1},
       "PremiumPro A9",
       "All-Apple household — wants best ecosystem fit"),

    _s("premium_android", "Premium — Premium Android Ecosystem",
       ["premium", "android"],
       {"sound_quality": 9, "noise_cancellation": 8, "call_quality": 8,
        "connectivity": 9, "comfort": 8, "price_to_value": 2},
       "PremiumPro A9",
       "Premium Android buyer — best sound and ANC"),

    _s("premium_business_travel", "Premium — Business Premium Traveler",
       ["premium", "business", "travel"],
       {"noise_cancellation": 10, "sound_quality": 9, "comfort": 9,
        "battery_life": 8, "call_quality": 7, "microphone_quality": 7, "price_to_value": 1},
       "PremiumPro A9",
       "Exec who travels weekly — premium sound + ANC in every dimension"),
]

# ── MICROPHONE FOCUS (8) ──────────────────────────────────────────────────────

MIC_SCENARIOS: list[OfflineScenario] = [
    _s("mic_podcaster", "Mic — Professional Podcaster",
       ["mic", "podcast", "studio"],
       {"microphone_quality": 10, "call_quality": 9, "sound_quality": 7,
        "noise_cancellation": 6, "comfort": 7, "price_to_value": 4},
       "WorkComfort W2",
       "Podcast recording — mic quality defines output"),

    _s("mic_youtuber", "Mic — YouTube Content Creator",
       ["mic", "youtube", "creator"],
       {"microphone_quality": 10, "call_quality": 8, "comfort": 7,
        "noise_cancellation": 6, "gaming_latency": 5, "price_to_value": 5},
       "WorkComfort W2",
       "Vlogging and video creation — mic + call quality"),

    _s("mic_corporate_meetings", "Mic — Corporate Meeting Host",
       ["mic", "meetings", "corporate"],
       {"microphone_quality": 10, "call_quality": 10, "noise_cancellation": 9,
        "comfort": 8, "battery_life": 8, "price_to_value": 3},
       "WorkComfort W2",
       "Hosts 4+ hour board meetings — crystal clear voice"),

    _s("mic_gamer_streamer", "Mic — Gamer & Twitch Streamer",
       ["mic", "gaming", "streaming"],
       {"microphone_quality": 10, "gaming_latency": 10, "call_quality": 8,
        "sound_quality": 7, "bass_response": 7, "comfort": 7, "price_to_value": 5},
       "GamingEar Q4",
       "Live streaming requires zero-latency + great mic"),

    _s("mic_asmr", "Mic — ASMR Creator",
       ["mic", "asmr", "creator"],
       {"microphone_quality": 10, "call_quality": 8, "comfort": 9,
        "noise_cancellation": 3, "price_to_value": 4},
       "WorkComfort W2",
       "ASMR requires capturing ultra-fine audio detail"),

    _s("mic_voice_actor", "Mic — Voice Actor",
       ["mic", "voice", "professional"],
       {"microphone_quality": 10, "call_quality": 10, "comfort": 8,
        "noise_cancellation": 6, "price_to_value": 3},
       "WorkComfort W2",
       "Professional voice acting — absolute mic precision"),

    _s("mic_musician_recording", "Mic — Musician (Recording Vocals)",
       ["mic", "music", "recording"],
       {"microphone_quality": 10, "call_quality": 8, "comfort": 7,
        "noise_cancellation": 5, "price_to_value": 4},
       "WorkComfort W2",
       "Records vocals at home — mic quality critical"),

    _s("mic_teacher_online", "Mic — Online Educator",
       ["mic", "teacher", "edu"],
       {"microphone_quality": 10, "call_quality": 10, "noise_cancellation": 8,
        "comfort": 9, "battery_life": 8, "price_to_value": 5},
       "WorkComfort W2",
       "3-hour online classes — mic + comfort all day"),
]

# ── COMFORT FOCUS (8) ─────────────────────────────────────────────────────────

COMFORT_SCENARIOS: list[OfflineScenario] = [
    _s("comfort_all_day_wear", "Comfort — All-Day Wear (10+ Hours)",
       ["comfort", "long-wear"],
       {"comfort": 10, "battery_life": 10, "water_resistance": 7, "durability": 8,
        "portability": 6, "price_to_value": 5},
       "AthleteFit G5",
       "10+ hours/day continuous wear — comfort first"),

    _s("comfort_sensitive_ears", "Comfort — Sensitive Ear Canals",
       ["comfort", "sensitive"],
       {"comfort": 10, "portability": 9, "sound_quality": 6,
        "battery_life": 6, "price_to_value": 7},
       "CompactBud C3",
       "Sensitive ears — must be featherlight and non-intrusive"),

    _s("comfort_glasses_wearer", "Comfort — Glasses Wearer",
       ["comfort", "glasses"],
       {"comfort": 10, "portability": 8, "sound_quality": 6,
        "noise_cancellation": 5, "price_to_value": 6},
       "CompactBud C3",
       "Wears glasses all day — nothing that presses on temples"),

    _s("comfort_hot_climate", "Comfort — Hot Climate / Sweating",
       ["comfort", "sweat", "climate"],
       {"water_resistance": 9, "comfort": 9, "durability": 8, "battery_life": 8,
        "portability": 7, "price_to_value": 5},
       "AthleteFit G5",
       "Extreme heat and sweat — waterproof + secure fit"),

    _s("comfort_small_ears", "Comfort — Small Ear Canals",
       ["comfort", "small-ears", "fit"],
       {"comfort": 10, "portability": 10, "sound_quality": 6,
        "battery_life": 6, "price_to_value": 7},
       "CompactBud C3",
       "Small ears — standard earbuds never fit right"),

    _s("comfort_sleep", "Comfort — Sleep Earbuds",
       ["comfort", "sleep"],
       {"comfort": 10, "portability": 10, "sound_quality": 6, "noise_cancellation": 5,
        "battery_life": 7, "price_to_value": 7},
       "CompactBud C3",
       "Wearing while sleeping — must be tiny and ultra-soft"),

    _s("comfort_large_ears", "Comfort — Large Ear Canals",
       ["comfort", "large-ears"],
       {"comfort": 10, "call_quality": 7, "microphone_quality": 6,
        "noise_cancellation": 4, "price_to_value": 5},
       "WorkComfort W2",
       "Large ear canals — proper ergonomic fit for extended office wear"),

    _s("comfort_neurodivergent", "Comfort — Sensory Sensitivity (Neurodivergent)",
       ["comfort", "sensory", "neurodivergent"],
       {"comfort": 10, "portability": 10, "price_to_value": 7, "battery_life": 5},
       "CompactBud C3",
       "Sensory overload triggers — lightest earbuds, non-intrusive"),
]

# ── COMMUTERS (7) ─────────────────────────────────────────────────────────────

COMMUTE_SCENARIOS: list[OfflineScenario] = [
    _s("commute_subway", "Commuter — Subway / Underground",
       ["commute", "subway", "anc"],
       {"noise_cancellation": 10, "sound_quality": 6, "portability": 6,
        "price_to_value": 4, "comfort": 7},
       "PremiumPro A9",
       "Subway noise is brutal — best ANC available"),

    _s("commute_bus", "Commuter — City Bus",
       ["commute", "bus", "balanced"],
       {"noise_cancellation": 7, "battery_life": 9, "portability": 8,
        "price_to_value": 8, "connectivity": 8, "sound_quality": 6},
       "MidRange M7",
       "Bus commute — balanced ANC + battery + price"),

    _s("commute_walking", "Commuter — Walking Commute",
       ["commute", "walking", "awareness"],
       {"transparency_mode": 10, "comfort": 7, "battery_life": 7,
        "portability": 7, "sound_quality": 5},
       "PremiumPro A9",
       "Walking through streets — transparency for street safety, premium earbuds excel"),

    _s("commute_cycling", "Commuter — Cycling Commuter",
       ["commute", "cycling", "safety"],
       {"transparency_mode": 10, "comfort": 7, "battery_life": 6,
        "portability": 6, "sound_quality": 5},
       "PremiumPro A9",
       "Cycling to work — traffic awareness is safety-critical, premium transparency"),

    _s("commute_long_90min", "Commuter — Long 90-Minute Commute",
       ["commute", "long", "battery"],
       {"battery_life": 9, "noise_cancellation": 7, "comfort": 8, "portability": 7,
        "price_to_value": 7, "connectivity": 8},
       "MidRange M7",
       "90-minute each way — battery + comfort + ANC + value"),

    _s("commute_weather", "Commuter — Rain & Wind Commuting",
       ["commute", "weather", "waterproof"],
       {"water_resistance": 10, "durability": 9, "noise_cancellation": 7, "battery_life": 8,
        "comfort": 7, "price_to_value": 5},
       "AthleteFit G5",
       "Rain + wind daily — must be waterproof and sturdy"),

    _s("commute_multimodal", "Commuter — Multi-Modal (Subway+Walk+Bus)",
       ["commute", "multi-modal"],
       {"battery_life": 9, "noise_cancellation": 7, "portability": 8,
        "price_to_value": 8, "connectivity": 9},
       "MidRange M7",
       "Needs ANC on subway and good battery for full commute"),
]

# ── APPLE ECOSYSTEM (5) ───────────────────────────────────────────────────────

APPLE_SCENARIOS: list[OfflineScenario] = [
    _s("apple_iphone_user", "Apple — iPhone Daily Driver",
       ["apple", "ecosystem", "iphone"],
       {"ecosystem_integration": 10, "sound_quality": 8, "noise_cancellation": 8,
        "call_quality": 7, "comfort": 7, "price_to_value": 3},
       "PremiumPro A9",
       "iPhone user wants seamless switching and Siri integration"),

    _s("apple_macbook_desk", "Apple — MacBook Power User",
       ["apple", "ecosystem", "desktop"],
       {"ecosystem_integration": 10, "call_quality": 9, "microphone_quality": 9,
        "sound_quality": 8, "noise_cancellation": 7, "price_to_value": 2},
       "PremiumPro A9",
       "MacBook user on calls all day — ecosystem + mic"),

    _s("apple_ipad_creative", "Apple — iPad Creative",
       ["apple", "ecosystem", "creative"],
       {"ecosystem_integration": 9, "sound_quality": 9, "comfort": 8,
        "noise_cancellation": 7, "price_to_value": 3},
       "PremiumPro A9",
       "iPad artist — Apple ecosystem + great sound"),

    _s("apple_student_ecosystem", "Apple — Student in Apple Ecosystem",
       ["apple", "ecosystem", "student"],
       {"ecosystem_integration": 8, "price_to_value": 5, "sound_quality": 7,
        "battery_life": 8, "noise_cancellation": 7, "comfort": 7},
       "PremiumPro A9",
       "Student with iPhone + MacBook — ecosystem benefit"),

    _s("apple_no_compromise", "Apple — Premium Apple All-In",
       ["apple", "premium", "ecosystem"],
       {"ecosystem_integration": 10, "sound_quality": 9, "noise_cancellation": 10,
        "comfort": 9, "call_quality": 9, "price_to_value": 1},
       "PremiumPro A9",
       "Budget is unlimited, must have best Apple experience"),
]

# ── ANDROID ECOSYSTEM (5) ─────────────────────────────────────────────────────

ANDROID_SCENARIOS: list[OfflineScenario] = [
    _s("android_pixel_user", "Android — Pixel User",
       ["android", "ecosystem", "pixel"],
       {"connectivity": 9, "price_to_value": 8, "battery_life": 8,
        "sound_quality": 6, "comfort": 7},
       "MidRange M7",
       "Pixel user — Google connectivity, value, balanced quality"),

    _s("android_samsung_user", "Android — Samsung Power User",
       ["android", "ecosystem", "samsung"],
       {"connectivity": 9, "price_to_value": 8, "battery_life": 8,
        "sound_quality": 6, "comfort": 7},
       "MidRange M7",
       "Samsung phone user — connectivity + balance"),

    _s("android_budget_android", "Android — Budget Android",
       ["android", "budget"],
       {"price_to_value": 9, "connectivity": 7, "durability": 7,
        "battery_life": 7, "sound_quality": 5},
       "BudgetBuds X3",
       "Android user on budget — value first"),

    _s("android_cross_platform", "Android — Cross-Platform (Phone + Laptop)",
       ["android", "cross-platform"],
       {"connectivity": 10, "battery_life": 8, "price_to_value": 7,
        "sound_quality": 6, "comfort": 7},
       "MidRange M7",
       "Switches between Android + Windows — multipoint connection"),

    _s("android_premium", "Android — Premium Android Buyer",
       ["android", "premium"],
       {"sound_quality": 9, "noise_cancellation": 8, "call_quality": 8,
        "connectivity": 9, "comfort": 8, "price_to_value": 3},
       "PremiumPro A9",
       "Premium Android phone — wants flagship earbuds"),
]


# ── GAMING (5) ────────────────────────────────────────────────────────────────

GAMING_SCENARIOS: list[OfflineScenario] = [
    _s("gaming_competitive_fps", "Gaming — Competitive FPS Player",
       ["gaming", "fps", "competitive"],
       {"gaming_latency": 10, "sound_quality": 8, "microphone_quality": 9,
        "comfort": 8, "price_to_value": 5, "bass_response": 6},
       "GamingEar Q4",
       "Competitive FPS — zero latency is game-winning"),

    _s("gaming_casual_mobile", "Gaming — Casual Mobile Gamer",
       ["gaming", "mobile", "casual"],
       {"gaming_latency": 5, "battery_life": 9, "sound_quality": 7,
        "price_to_value": 7, "comfort": 7, "connectivity": 6},
       "MidRange M7",
       "Mobile gaming — battery + balance more important than low latency"),

    _s("gaming_streamer_pc", "Gaming — PC Streamer",
       ["gaming", "streaming", "pc"],
       {"microphone_quality": 10, "gaming_latency": 9, "sound_quality": 8,
        "call_quality": 8, "comfort": 8, "price_to_value": 5},
       "GamingEar Q4",
       "PC streamer — mic + latency for live stream"),

    _s("gaming_console", "Gaming — Console (PlayStation/Xbox) Gamer",
       ["gaming", "console"],
       {"gaming_latency": 9, "sound_quality": 8, "microphone_quality": 8,
        "bass_response": 7, "comfort": 7, "price_to_value": 6},
       "GamingEar Q4",
       "Console gaming — latency + mic for party chat"),

    _s("gaming_budget_student", "Gaming — Budget Gamer Student",
       ["gaming", "budget", "student"],
       {"price_to_value": 7, "gaming_latency": 8, "microphone_quality": 8,
        "sound_quality": 6, "comfort": 6},
       "GamingEar Q4",
       "Student gamer — wants gaming latency improvement, decent price"),
]


# ── CONSTRAINT ENFORCEMENT SCENARIOS (5) ─────────────────────────────────────
# These directly test that hard constraints lower scores for violating products.

CONSTRAINT_SCENARIOS: list[OfflineScenario] = [
    _s(
        "constraint_anc_required",
        "Constraint — ANC Is Hard Requirement",
        ["constraint", "anc"],
        {"noise_cancellation": 10, "sound_quality": 7, "battery_life": 7,
         "comfort": 7, "price_to_value": 5},
        "PremiumPro A9",
        "User said MUST have ANC — low-ANC products should rank last",
        not_rank_1=["BudgetBuds X3", "AthleteFit G5"],
        intent={
            "hard_constraints": ["must have active noise cancellation"],
            "budget": None, "preferences": [], "exclusions": [], "uncertainties": [],
        },
    ),
    _s(
        "constraint_waterproof_required",
        "Constraint — Waterproof Is Hard Requirement",
        ["constraint", "waterproof"],
        {"water_resistance": 10, "durability": 9, "comfort": 8,
         "battery_life": 7, "price_to_value": 5},
        "AthleteFit G5",
        "User said MUST be waterproof — GamingEar (IPX0) should rank last",
        not_rank_1=["GamingEar Q4", "BudgetBuds X3"],
        intent={
            "hard_constraints": ["must be waterproof / IPX rating"],
            "budget": None, "preferences": [], "exclusions": [], "uncertainties": [],
        },
    ),
    _s(
        "constraint_budget_hard",
        "Constraint — Budget Hard Cap",
        ["constraint", "budget"],
        {"price_to_value": 10, "durability": 7, "battery_life": 7,
         "sound_quality": 5, "comfort": 5},
        "BudgetBuds X3",
        "User said budget is under ₹3000 — PremiumPro should rank last",
        not_rank_1=["PremiumPro A9", "AudioPhile H1"],
        intent={
            "hard_constraints": ["budget under ₹3000"],
            "budget": "under ₹3000", "preferences": [], "exclusions": [], "uncertainties": [],
        },
    ),
    _s(
        "constraint_gaming_latency",
        "Constraint — Gaming Latency Hard Requirement",
        ["constraint", "gaming"],
        {"gaming_latency": 10, "microphone_quality": 8, "sound_quality": 7,
         "comfort": 7, "price_to_value": 6},
        "GamingEar Q4",
        "User said MUST have low-latency gaming mode",
        intent={
            "hard_constraints": ["must have gaming low-latency mode"],
            "budget": None, "preferences": [], "exclusions": [], "uncertainties": [],
        },
    ),
    _s(
        "constraint_exclusion_over_ear",
        "Constraint — Excludes In-Ear Style",
        ["constraint", "exclusion"],
        {"portability": 10, "comfort": 9, "price_to_value": 7, "battery_life": 6},
        "CompactBud C3",
        "User excluded large/over-ear — smallest earbuds win",
        intent={
            "hard_constraints": [],
            "budget": None, "preferences": ["true wireless only"],
            "exclusions": ["no over-ear headphones", "no large earbuds"],
            "uncertainties": [],
        },
    ),
]

# ── Master export ──────────────────────────────────────────────────────────────

def all_scenarios() -> list[OfflineScenario]:
    return (
        STUDENT_SCENARIOS
        + GYM_SCENARIOS
        + TRAVELER_SCENARIOS
        + OFFICE_SCENARIOS
        + AUDIOPHILE_SCENARIOS
        + BUDGET_SCENARIOS
        + PREMIUM_SCENARIOS
        + MIC_SCENARIOS
        + COMFORT_SCENARIOS
        + COMMUTE_SCENARIOS
        + APPLE_SCENARIOS
        + ANDROID_SCENARIOS
        + GAMING_SCENARIOS
        + CONSTRAINT_SCENARIOS
    )


def scenarios_by_tag(tag: str) -> list[OfflineScenario]:
    return [s for s in all_scenarios() if tag in s.tags]
