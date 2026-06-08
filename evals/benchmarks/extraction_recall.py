"""
Fix 18: Extraction Recall Benchmarks

Measures whether the normalization/extraction pipeline correctly preserves
all expected products through deduplication, capping, and name normalization.

Each ExtractionScenario carries a raw analysis JSON (as produced by analyzer.py)
together with the ground-truth expected product list.  The metric runs
normalize_analysis() and checks recall — no LLM calls required.

Why this matters: if the top product in the market never survives normalization,
it can never win — but no other eval catches that.
"""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class ExtractionScenario:
    id: str
    description: str
    category: str
    # Raw analysis dict — same shape as analyzer.py output, passed to normalize_analysis()
    analysis_json: dict
    # Products that MUST appear in the normalized output (lowercase, exact or fuzzy match)
    expected_products: list[str]
    # Products that should NOT appear (hallucinations we injected to catch over-extraction)
    unexpected_products: list[str] = field(default_factory=list)
    # Minimum recall threshold for this scenario (0.0–1.0)
    min_recall: float = 1.0


def all_extraction_scenarios() -> list[ExtractionScenario]:
    return [
        # ── Scenario 1: Basic earbuds — all mainstream products should survive ──
        ExtractionScenario(
            id="ext-001",
            description="Earbuds corpus — top 5 products must be extracted",
            category="electronics/earbuds",
            analysis_json={
                "summary": "Community discussion on best wireless earbuds under ₹5000.",
                "products": [
                    {
                        "name": "Sony WF-C500",
                        "mention_count": 45,
                        "distinct_recommenders": 32,
                        "positive_mentions": 38,
                        "negative_mentions": 7,
                        "praise": ["great ANC", "comfortable fit"],
                        "complaints": [{"text": "battery life average", "confidence": "reported"}],
                        "sources": ["reddit:IndianGaming", "review:91mobiles.com"],
                        "signal_strength": "high",
                        "representative_quote": "Best in class for the price.",
                    },
                    {
                        "name": "Boat Airdopes 141",
                        "mention_count": 38,
                        "distinct_recommenders": 27,
                        "positive_mentions": 31,
                        "negative_mentions": 7,
                        "praise": ["bass heavy", "budget friendly"],
                        "complaints": [{"text": "mic quality poor", "confidence": "confirmed"}],
                        "sources": ["reddit:IndiaGadgets"],
                        "signal_strength": "high",
                        "representative_quote": "Good value for money.",
                    },
                    {
                        "name": "Realme Buds Air 3",
                        "mention_count": 29,
                        "distinct_recommenders": 20,
                        "positive_mentions": 23,
                        "negative_mentions": 6,
                        "praise": ["ANC at this price"],
                        "complaints": [],
                        "sources": ["reddit:IndianGaming", "review:digit.in"],
                        "signal_strength": "moderate",
                        "representative_quote": "",
                    },
                    {
                        "name": "JBL Tune 230NC TWS",
                        "mention_count": 22,
                        "distinct_recommenders": 16,
                        "positive_mentions": 18,
                        "negative_mentions": 4,
                        "praise": ["JBL sound signature"],
                        "complaints": [{"text": "case build quality", "confidence": "single"}],
                        "sources": ["review:gadgets360.com"],
                        "signal_strength": "moderate",
                        "representative_quote": "",
                    },
                    {
                        "name": "Noise Buds VS104",
                        "mention_count": 18,
                        "distinct_recommenders": 12,
                        "positive_mentions": 14,
                        "negative_mentions": 4,
                        "praise": ["long battery"],
                        "complaints": [],
                        "sources": ["reddit:frugalIndia"],
                        "signal_strength": "moderate",
                        "representative_quote": "",
                    },
                ],
                "materials": [],
            },
            expected_products=[
                "sony wf-c500",
                "boat airdopes 141",
                "realme buds air 3",
                "jbl tune 230nc tws",
                "noise buds vs104",
            ],
            unexpected_products=["phantom product xyz", "nonexistent brand abc"],
            min_recall=1.0,
        ),

        # ── Scenario 2: Laptops — dedup must not merge different models ──
        ExtractionScenario(
            id="ext-002",
            description="Laptops — dedup must keep similar-named distinct models",
            category="electronics/laptop",
            analysis_json={
                "summary": "Budget laptop recommendations for students.",
                "products": [
                    {
                        "name": "Acer Aspire 5",
                        "mention_count": 60,
                        "distinct_recommenders": 40,
                        "positive_mentions": 50,
                        "negative_mentions": 10,
                        "praise": ["great build", "IPS display"],
                        "complaints": [],
                        "sources": ["reddit:SuggestALaptop", "review:rtings.com"],
                        "signal_strength": "high",
                        "representative_quote": "Best sub-500 dollar laptop.",
                    },
                    {
                        "name": "Acer Aspire 3",
                        "mention_count": 35,
                        "distinct_recommenders": 22,
                        "positive_mentions": 28,
                        "negative_mentions": 7,
                        "praise": ["affordable", "good battery"],
                        "complaints": [{"text": "TN panel dim", "confidence": "confirmed"}],
                        "sources": ["reddit:SuggestALaptop"],
                        "signal_strength": "moderate",
                        "representative_quote": "",
                    },
                    {
                        "name": "ASUS VivoBook 15",
                        "mention_count": 42,
                        "distinct_recommenders": 30,
                        "positive_mentions": 36,
                        "negative_mentions": 6,
                        "praise": ["slim design", "fast SSD"],
                        "complaints": [],
                        "sources": ["review:notebookcheck.net", "reddit:laptops"],
                        "signal_strength": "high",
                        "representative_quote": "",
                    },
                    {
                        "name": "Lenovo IdeaPad Slim 3",
                        "mention_count": 30,
                        "distinct_recommenders": 20,
                        "positive_mentions": 24,
                        "negative_mentions": 6,
                        "praise": ["reliable", "keyboard"],
                        "complaints": [],
                        "sources": ["reddit:IndiaGadgets"],
                        "signal_strength": "moderate",
                        "representative_quote": "",
                    },
                ],
                "materials": [],
            },
            expected_products=[
                "acer aspire 5",
                "acer aspire 3",
                "asus vivobook 15",
                "lenovo ideapad slim 3",
            ],
            unexpected_products=["acer aspire x99"],
            min_recall=1.0,
        ),

        # ── Scenario 3: Noisy LLM output — non-standard field types must survive ──
        ExtractionScenario(
            id="ext-003",
            description="Noisy LLM output with string counts and nested lists",
            category="electronics/headphones",
            analysis_json={
                "summary": "Over-ear headphone recommendations.",
                "products": [
                    {
                        "name": "Sony WH-1000XM5",
                        # String counts (LLM sometimes returns strings)
                        "mention_count": "52",
                        "distinct_recommenders": "38",
                        "positive_mentions": "44+",
                        "negative_mentions": "8",
                        "praise": [["best ANC"], "comfortable"],  # nested list
                        "complaints": "build feels plasticky",     # string instead of list
                        "sources": ["reddit:Headphones", "review:rtings.com", "review:rtings.com"],  # duplicate
                        "signal_strength": "high",
                        "representative_quote": "Industry-leading noise cancellation.",
                    },
                    {
                        "name": "Bose QuietComfort 45",
                        "mention_count": "40",
                        "distinct_recommenders": "28",
                        "positive_mentions": "35",
                        "negative_mentions": "5",
                        "praise": ["comfort", "sound quality"],
                        "complaints": [{"text": "expensive", "confidence": "confirmed"}],
                        "sources": ["reddit:Headphones"],
                        "signal_strength": "high",
                        "representative_quote": "",
                    },
                    {
                        "name": "Jabra Evolve2 55",
                        "mention_count": 18,
                        "distinct_recommenders": 12,
                        "positive_mentions": 14,
                        "negative_mentions": 4,
                        "praise": ["enterprise-grade mic"],
                        "complaints": [],
                        "sources": ["review:rtings.com"],
                        "signal_strength": "moderate",
                        "representative_quote": "",
                    },
                ],
                "materials": [],
            },
            expected_products=[
                "sony wh-1000xm5",
                "bose quietcomfort 45",
                "jabra evolve2 55",
            ],
            min_recall=1.0,
        ),

        # ── Scenario 4: Products at exactly the cap boundary ──────────────────
        ExtractionScenario(
            id="ext-004",
            description="Products at MAX_PRODUCTS cap — first 50 must all survive",
            category="general/product",
            analysis_json={
                "summary": "Many products mentioned.",
                "products": [
                    {
                        "name": f"Product {i:02d}",
                        "mention_count": 50 - i,
                        "distinct_recommenders": max(1, 30 - i),
                        "positive_mentions": max(0, 40 - i),
                        "negative_mentions": min(10, i),
                        "praise": ["good"],
                        "complaints": [],
                        "sources": [f"reddit:sub{i}"],
                        "signal_strength": "moderate",
                        "representative_quote": "",
                    }
                    for i in range(48)  # 48 products — safely under the 50-cap
                ],
                "materials": [],
            },
            expected_products=[f"product {i:02d}" for i in range(48)],
            min_recall=1.0,
        ),

        # ── Scenario 5: Empty products list — must return empty, no crash ──────
        ExtractionScenario(
            id="ext-005",
            description="Empty products list — normalize must not crash",
            category="general/product",
            analysis_json={
                "summary": "No products found.",
                "products": [],
                "materials": [],
            },
            expected_products=[],
            min_recall=1.0,  # vacuously true — 0/0 recall = 1.0
        ),

        # ── Scenario 6: Source coverage — distinct sources tracked correctly ──
        ExtractionScenario(
            id="ext-006",
            description="Source coverage — distinct sources must be counted correctly",
            category="electronics/smartphone",
            analysis_json={
                "summary": "Smartphone comparison.",
                "products": [
                    {
                        "name": "Samsung Galaxy S24",
                        "mention_count": 55,
                        "distinct_recommenders": 40,
                        "positive_mentions": 45,
                        "negative_mentions": 10,
                        "praise": ["great camera", "build quality"],
                        "complaints": [],
                        "sources": [
                            "reddit:Android", "reddit:Android",  # duplicate
                            "review:91mobiles.com",
                            "review:gadgets360.com",
                            "review:gsmarena.com",
                        ],
                        "signal_strength": "high",
                        "representative_quote": "Best Android flagship.",
                    },
                    {
                        "name": "Google Pixel 8",
                        "mention_count": 40,
                        "distinct_recommenders": 30,
                        "positive_mentions": 35,
                        "negative_mentions": 5,
                        "praise": ["pure Android", "camera AI"],
                        "complaints": [],
                        "sources": ["reddit:Android", "review:gsmarena.com"],
                        "signal_strength": "high",
                        "representative_quote": "",
                    },
                ],
                "materials": [],
            },
            expected_products=["samsung galaxy s24", "google pixel 8"],
            min_recall=1.0,
        ),
    ]
