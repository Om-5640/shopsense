from types import SimpleNamespace

from product_canonicalizer import canonicalize_product
from product_link_intel import ProductCandidate, compute_consensus_score
from product_matcher import match_product_candidate
import price_fetcher


def test_matcher_handles_compact_model_alias():
    canonical = canonicalize_product("Sony WF-1000XM5")
    result = match_product_candidate(canonical, "Sony WF1000XM5 Noise Cancelling Earbuds")

    assert result.model_match == 1.0
    assert result.overall_match_score >= 0.85


def test_matcher_penalizes_variant_mismatch():
    canonical = canonicalize_product("Samsung Galaxy S25 Ultra 256GB")

    exact = match_product_candidate(canonical, "Samsung Galaxy S25 Ultra 256GB Titanium Black")
    wrong_variant = match_product_candidate(canonical, "Samsung Galaxy S25 Plus 256GB Pink")

    assert wrong_variant.overall_match_score < exact.overall_match_score
    assert wrong_variant.overall_match_score <= 0.55


def test_link_consensus_splits_across_variants():
    candidates = [
        ProductCandidate(
            retailer_name="Amazon",
            title="Apple iPhone 15 Pro 256GB",
            url="https://www.amazon.com/iphone-15-pro-256",
            price=999.0,
            rating=4.7,
            review_count=1200,
            image_url=None,
            mrp=None,
            domain="amazon.com",
            raw={},
        ),
        ProductCandidate(
            retailer_name="Best Buy",
            title="Apple iPhone 15 Pro 128GB",
            url="https://www.bestbuy.com/iphone-15-pro-128",
            price=899.0,
            rating=4.6,
            review_count=800,
            image_url=None,
            mrp=None,
            domain="bestbuy.com",
            raw={},
        ),
    ]

    assert compute_consensus_score(candidates) == 0.5


def test_price_parsers_ignore_storage_numbers():
    assert price_fetcher._parse_inr("12GB RAM + 256GB Storage for ₹24,999") == 24999
    assert price_fetcher._parse_usd("Only $1,299.99, save $200 today") == 1299
    assert price_fetcher._parse_gbp("£999.00 with £120 trade-in bonus") == 999


def test_best_price_ignores_storage_mismatch_when_intel_marks_it(monkeypatch):
    amazon = {
        "name": "Amazon India",
        "price_inr": 31999,
        "url": "https://www.amazon.in/s25-ultra-128",
        "title": "Samsung Galaxy S25 Ultra 128GB",
        "_candidates": [],
    }
    flipkart = {
        "name": "Flipkart",
        "price_inr": 42999,
        "url": "https://www.flipkart.com/s25-ultra-256",
        "title": "Samsung Galaxy S25 Ultra 256GB",
        "_candidates": [],
    }

    monkeypatch.setattr(price_fetcher, "_price_cache_get", lambda key: None)
    monkeypatch.setattr(price_fetcher, "_price_cache_set", lambda key, value: None)
    monkeypatch.setattr(price_fetcher, "_canonicalize", canonicalize_product)
    monkeypatch.setattr(price_fetcher, "_HAS_LINK_INTEL", True)
    monkeypatch.setattr(price_fetcher, "LINK_INTEL_ENABLED", True)
    monkeypatch.setitem(
        price_fetcher._RETAILER_FETCHERS,
        "india",
        [lambda _: dict(amazon), lambda _: dict(flipkart)],
    )

    amazon_candidate = SimpleNamespace(
        domain="amazon.in",
        retailer_name="Amazon India",
        raw=dict(amazon),
        match_score=0.18,
        storage_mismatch=True,
        price=31999.0,
        review_count=10,
    )
    flipkart_candidate = SimpleNamespace(
        domain="flipkart.com",
        retailer_name="Flipkart",
        raw=dict(flipkart),
        match_score=0.91,
        storage_mismatch=False,
        price=42999.0,
        review_count=400,
    )

    class FakeIntel:
        best_candidate = flipkart_candidate
        all_candidates = [amazon_candidate, flipkart_candidate]
        status = "uncertain"

        def to_dict(self):
            return {
                "status": self.status,
                "best_url": self.best_candidate.raw["url"],
                "match_score": self.best_candidate.match_score,
            }

    monkeypatch.setattr(price_fetcher, "run_link_intelligence", lambda *args, **kwargs: FakeIntel())

    result = price_fetcher._fetch_one_product("Samsung Galaxy S25 Ultra 256GB", "india")

    assert result["best_price"] == {"retailer": "Flipkart", "price_inr": 42999}
    assert result["retailers"][0]["storage_mismatch"] is True
    assert result["retailers"][1]["storage_mismatch"] is False
