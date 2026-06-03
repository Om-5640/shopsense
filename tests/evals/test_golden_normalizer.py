"""
Golden-file tests for analysis_normalizer.normalize_analysis().

Each test replays a recorded LLM output shape through the normalizer and
asserts the output matches the known-good snapshot stored in fixtures/.

These tests catch silent regressions when:
  - A provider updates its model and changes output shape
  - Someone edits normalize_analysis() and breaks an edge case
  - A new LLM-output quirk is discovered and a fixture is added

Adding a new provider quirk: create a fixture JSON in tests/evals/fixtures/,
run `python -m pytest tests/evals/ -k <fixture_id>` to verify, then commit.
"""

from __future__ import annotations

import pytest
from analysis_normalizer import normalize_analysis
from tests.evals.conftest import (
    load_fixture, all_normalizer_fixtures, assert_product_schema,
    REQUIRED_PRODUCT_KEYS,
)


# ---------------------------------------------------------------------------
# Parametrised: every fixture gets its own test case
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fixture_id", all_normalizer_fixtures())
def test_normalizer_never_crashes(fixture_id: str):
    """normalize_analysis must never raise regardless of input shape."""
    f = load_fixture(fixture_id)
    result = normalize_analysis(f["raw_llm_output"])
    assert isinstance(result, dict)
    assert "summary" in result
    assert "products" in result
    assert "materials" in result
    assert isinstance(result["products"], list)
    assert isinstance(result["materials"], list)


@pytest.mark.parametrize("fixture_id", all_normalizer_fixtures())
def test_normalizer_product_schema(fixture_id: str):
    """Every product in the output must have the full canonical schema."""
    f = load_fixture(fixture_id)
    result = normalize_analysis(f["raw_llm_output"])
    for product in result["products"]:
        assert_product_schema(product)


# ---------------------------------------------------------------------------
# Per-fixture assertion: validate expected properties
# ---------------------------------------------------------------------------

def test_standard_earbuds_product_count():
    f = load_fixture("earbuds_standard")
    result = normalize_analysis(f["raw_llm_output"])
    assert len(result["products"]) == f["expected"]["product_count"]


def test_standard_earbuds_summary_nonempty():
    f = load_fixture("earbuds_standard")
    result = normalize_analysis(f["raw_llm_output"])
    assert result["summary"] != ""


def test_standard_earbuds_top_product_signal():
    f = load_fixture("earbuds_standard")
    result = normalize_analysis(f["raw_llm_output"])
    xm5 = next((p for p in result["products"] if "WF-1000XM5" in p["name"]), None)
    assert xm5 is not None, "Sony WF-1000XM5 not found in products"
    assert xm5["signal_strength"] == "high"
    assert xm5["mention_count"] >= 40


def test_standard_earbuds_materials():
    f = load_fixture("earbuds_standard")
    result = normalize_analysis(f["raw_llm_output"])
    assert len(result["materials"]) == f["expected"]["materials_count"]


def test_malformed_counts_mention_count_not_shadowed():
    """Bug 1/2: mention_count=0 must NOT fall through to mentions=30."""
    f = load_fixture("earbuds_malformed_counts")
    result = normalize_analysis(f["raw_llm_output"])
    by_name = {p["name"]: p for p in result["products"]}

    sony = by_name.get("Sony WF-1000XM5")
    assert sony is not None
    assert sony["mention_count"] == 5, (
        f"Expected 5 (from '5+'), got {sony['mention_count']} — "
        f"Bug 1/2: zero/low mention_count must not fall back to 'mentions' field"
    )

    airpods = by_name.get("Apple AirPods Pro 2")
    assert airpods is not None
    assert airpods["mention_count"] == 0, (
        f"Expected 0, got {airpods['mention_count']} — "
        f"mention_count=0 must not be replaced by mentions=30"
    )


def test_malformed_counts_negative_clamped():
    """Bug 3: negative counts must be floored to 0."""
    f = load_fixture("earbuds_malformed_counts")
    result = normalize_analysis(f["raw_llm_output"])
    sony = next((p for p in result["products"] if "WF-1000XM5" in p["name"]), None)
    assert sony is not None
    assert sony["negative_mentions"] >= 0, (
        f"negative_mentions was {sony['negative_mentions']} — must be >= 0 (Bug 3)"
    )


def test_nested_complaints_flattened():
    """Bug 4: [[c1, c2], c3] in complaints must be flattened to [c1, c2, c3]."""
    f = load_fixture("earbuds_nested_complaints")
    result = normalize_analysis(f["raw_llm_output"])
    by_name = {p["name"]: p for p in result["products"]}

    sony = by_name.get("Sony WF-1000XM5")
    assert sony is not None
    assert len(sony["complaints"]) == 3, (
        f"Expected 3 complaints (flattened from [[c1,c2],c3]), got {len(sony['complaints'])} — Bug 4"
    )

    jabra = by_name.get("Jabra Elite 5")
    assert jabra is not None
    assert len(jabra["complaints"]) == 3, (
        f"Expected 3 complaints (flattened from [[dict,dict],dict]), got {len(jabra['complaints'])} — Bug 4"
    )


def test_duplicate_products_merged():
    """Bug 5/6: 'Sony WF-1000XM5' and 'Sony WF1000XM5' must merge into one product."""
    f = load_fixture("earbuds_duplicate_products")
    result = normalize_analysis(f["raw_llm_output"])
    assert len(result["products"]) == 2, (
        f"Expected 2 unique products after dedup, got {len(result['products'])} — Bug 5/6"
    )
    sony_products = [p for p in result["products"] if "Sony" in p["name"] or "sony" in p["name"].lower()]
    assert len(sony_products) == 1, "Sony WF-1000XM5 variants should merge into one"
    assert sony_products[0]["mention_count"] >= 28, "Merged mention counts should sum to >=28"


def test_duplicate_products_praise_accumulated():
    """Merged product praise list must contain entries from both duplicates."""
    f = load_fixture("earbuds_duplicate_products")
    result = normalize_analysis(f["raw_llm_output"])
    sony = next((p for p in result["products"] if "Sony" in p["name"]), None)
    assert sony is not None
    assert len(sony["praise"]) >= 3, (
        f"Expected at least 3 praise items from merge, got {len(sony['praise'])}"
    )


def test_string_products_get_full_schema():
    """Bug 7: bare-string products must receive full canonical schema."""
    f = load_fixture("earbuds_string_products")
    result = normalize_analysis(f["raw_llm_output"])
    assert len(result["products"]) == 3
    for p in result["products"]:
        assert_product_schema(p)
        assert p["praise"] == []
        assert p["complaints"] == []
        assert p["mention_count"] == 0


def test_alternate_field_names_resolved():
    """LLM alternate field names (product_name, brand_model) must be resolved to 'name'."""
    f = load_fixture("earbuds_alternate_field_names")
    result = normalize_analysis(f["raw_llm_output"])
    names = {p["name"] for p in result["products"]}
    assert "Sony WF-1000XM5" in names, f"product_name field not resolved. Got: {names}"
    assert "Jabra Elite 5"   in names, f"brand_model field not resolved. Got: {names}"


def test_invalid_signal_strength_normalised():
    """signal_strength values not in {high, medium, low} must become 'low'."""
    f = load_fixture("earbuds_invalid_signal_strength")
    result = normalize_analysis(f["raw_llm_output"])
    by_name = {p["name"]: p for p in result["products"]}

    sony = by_name["Sony WF-1000XM5"]
    assert sony["signal_strength"] == "low", (
        f"'excellent' should normalise to 'low', got '{sony['signal_strength']}'"
    )
    random = by_name["Random Budget Buds"]
    assert random["signal_strength"] == "low", (
        f"'5/10' should normalise to 'low', got '{random['signal_strength']}'"
    )
    jabra = by_name["Jabra Elite 5"]
    assert jabra["signal_strength"] == "medium"  # valid — must be unchanged


def test_none_input_no_crash():
    """normalize_analysis(None) must return canonical empty structure."""
    f = load_fixture("earbuds_none_input")
    result = normalize_analysis(f["raw_llm_output"])  # raw_llm_output is null → None
    assert result["products"] == []
    assert result["summary"] == ""
    assert result["materials"] == []


def test_array_caps_enforced():
    """Bug 8: praise/complaints/sources exceeding caps must be truncated."""
    f = load_fixture("earbuds_array_caps")
    result = normalize_analysis(f["raw_llm_output"])
    assert len(result["products"]) == 1
    p = result["products"][0]
    assert len(p["praise"])      <= 20, f"praise cap exceeded: {len(p['praise'])}"
    assert len(p["complaints"])  <= 20, f"complaints cap exceeded: {len(p['complaints'])}"
    assert len(p["sources"])     <= 50, f"sources cap exceeded: {len(p['sources'])}"


def test_smartphones_correct_count():
    f = load_fixture("smartphones_standard")
    result = normalize_analysis(f["raw_llm_output"])
    assert len(result["products"]) == 4
    assert len(result["materials"]) == 1


def test_smartphones_product_names():
    f = load_fixture("smartphones_standard")
    result = normalize_analysis(f["raw_llm_output"])
    names = {p["name"] for p in result["products"]}
    assert "OnePlus 12" in names
    assert "Samsung Galaxy S24 Ultra" in names
    assert "iPhone 15 Pro" in names
    assert "Google Pixel 8 Pro" in names


def test_skincare_non_tech_category():
    """Non-tech categories (skincare) must work identically."""
    f = load_fixture("skincare_standard")
    result = normalize_analysis(f["raw_llm_output"])
    assert len(result["products"]) == 3
    assert len(result["materials"]) == 2
    for p in result["products"]:
        assert_product_schema(p)


def test_laptops_standard():
    f = load_fixture("laptops_standard")
    result = normalize_analysis(f["raw_llm_output"])
    assert len(result["products"]) == 3
    names = {p["name"] for p in result["products"]}
    assert "ASUS TUF Gaming A15" in names
    assert "Apple MacBook Air M2" in names
