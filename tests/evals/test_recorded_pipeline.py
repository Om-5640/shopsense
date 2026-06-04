"""
Recorded real-pipeline replay tests.

These run in CI, deterministically, with zero API calls. They replay committed real
pipeline outputs and assert the qualities that the synthetic offline benchmark cannot:

  - Extraction recall: every product the source text discusses was extracted
  - Evidence grounding: criteria cite real evidence, not "no data found" placeholders
  - Retrieval coverage: each product carries praise, complaints, and community signal
  - No hallucinated products: every scored product is one the source actually discusses

If a future model change degrades extraction or starts emitting ungrounded evidence,
these fail loudly — the regression gate the synthetic benchmark can't provide.

Recapture fixtures after a real run:  python -m evals.online.record
"""

from __future__ import annotations

import pytest

from tests.evals.conftest import load_fixture  # noqa: F401 (ensures sys.path + dummy keys)
from evals.benchmarks.recorded import load_recorded_fixtures

_FIXTURES = load_recorded_fixtures()
_IDS = [f.get("_meta", {}).get("query", f"fixture_{i}") for i, f in enumerate(_FIXTURES)]

_DEFAULT_EVIDENCE = (
    "no direct data found", "no evidence", "insufficient data",
    "not mentioned", "unclear from research", "benchmark synthetic data",
)


def _canon(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def test_recorded_fixtures_exist():
    assert _FIXTURES, "at least one recorded pipeline fixture must be committed for CI replay"


@pytest.mark.skipif(not _FIXTURES, reason="no recorded fixtures")
@pytest.mark.parametrize("fixture", _FIXTURES, ids=_IDS)
def test_extraction_recall(fixture):
    """Every product the source text discusses must appear in the scored output."""
    meta = fixture.get("_meta", {})
    expected = meta.get("expected_products", [])
    scored = {_canon(p["name"]) for p in fixture.get("scored_products", [])}
    missing = [e for e in expected if _canon(e) not in scored]
    assert not missing, f"extraction missed expected products: {missing}"


@pytest.mark.skipif(not _FIXTURES, reason="no recorded fixtures")
@pytest.mark.parametrize("fixture", _FIXTURES, ids=_IDS)
def test_no_hallucinated_products(fixture):
    """Every scored product must be one the recorded source actually discusses."""
    meta = fixture.get("_meta", {})
    allowed = {_canon(e) for e in meta.get("expected_products", [])}
    source = _canon(meta.get("source_excerpt", ""))
    for p in fixture.get("scored_products", []):
        c = _canon(p["name"])
        assert c in allowed or c in source, f"hallucinated product not in source: {p['name']}"


@pytest.mark.skipif(not _FIXTURES, reason="no recorded fixtures")
@pytest.mark.parametrize("fixture", _FIXTURES, ids=_IDS)
def test_evidence_is_grounded(fixture):
    """No product may have its evidence dominated by default/no-data placeholders."""
    for p in fixture.get("scored_products", []):
        scores = p.get("scores", [])
        if not scores:
            continue
        default = sum(
            1 for s in scores
            if any(pat in (s.get("evidence") or "").lower() for pat in _DEFAULT_EVIDENCE)
        )
        assert default / len(scores) <= 0.5, (
            f"{p['name']}: {default}/{len(scores)} criteria have ungrounded evidence"
        )
        for s in scores:
            assert (s.get("evidence") or "").strip(), f"{p['name']}: empty evidence for {s.get('criterion')}"


@pytest.mark.skipif(not _FIXTURES, reason="no recorded fixtures")
@pytest.mark.parametrize("fixture", _FIXTURES, ids=_IDS)
def test_retrieval_coverage(fixture):
    """Each product must carry praise, complaints, and community mention signal."""
    for p in fixture.get("scored_products", []):
        assert p.get("praise"), f"{p['name']}: no praise extracted"
        assert p.get("complaints"), f"{p['name']}: no complaints extracted"
        assert int(p.get("mention_count", 0)) > 0, f"{p['name']}: zero mentions"


@pytest.mark.skipif(not _FIXTURES, reason="no recorded fixtures")
@pytest.mark.parametrize("fixture", _FIXTURES, ids=_IDS)
def test_online_metrics_pass_on_recorded(fixture):
    """The real online-quality metrics must clear their thresholds on recorded output."""
    from evals.metrics.retrieval_quality import RetrievalQualityMetric
    from evals.metrics.explanation_integrity import ExplanationIntegrityMetric

    pr = [{"scored_products": fixture.get("scored_products", [])}]
    rq = RetrievalQualityMetric().evaluate([], pipeline_results=pr)
    ei = ExplanationIntegrityMetric().evaluate([], pipeline_results=pr)
    assert not rq.skipped and rq.passed, f"retrieval_quality failed on recorded data: {rq.score}"
    assert not ei.skipped and ei.passed, f"explanation_integrity failed on recorded data: {ei.score}"
