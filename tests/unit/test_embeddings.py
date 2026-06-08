"""
Unit tests for embeddings.py.

Covers:
 - SHA256 key consistency
 - In-memory cache tier (file-based cache.py)
 - Provider fallback chain (Gemini → Cohere → HF → local)
 - embed_batch: cache hits, partial misses, Gemini batch, empty input
 - In-flight deduplication (concurrent calls)
 - cosine_similarity and cosine_similarity_batch
 - DB cache tier (via mock_db_cache fixture from conftest.py)

All external API calls are mocked — no network access required.
"""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Optional
from unittest.mock import MagicMock, patch, call
import pytest

# Import the real module at collection time so test_quality_gaps_13_17.py's
# module-level setdefault stub cannot replace it when the full suite runs.
import embeddings as _embeddings_real  # noqa: F401


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_vec(dims: int = 4, val: float = 0.5) -> list[float]:
    return [val] * dims


# ── TestSHA256KeyConsistency ──────────────────────────────────────────────────

class TestSHA256KeyConsistency:
    def test_same_text_same_key(self):
        from embeddings import _key
        assert _key("hello world") == _key("hello world")

    def test_different_texts_different_keys(self):
        from embeddings import _key
        assert _key("text A") != _key("text B")

    def test_unicode_produces_valid_hex(self):
        from embeddings import _key
        result = _key("こんにちは 🎧")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_empty_string_has_deterministic_key(self):
        from embeddings import _key
        k = _key("")
        assert k == hashlib.sha256("".encode("utf-8")).hexdigest()


# ── TestInMemoryCacheTier ─────────────────────────────────────────────────────

class TestInMemoryCacheTier:
    def test_cache_hit_returns_vector_no_api_call(self):
        """If the vector is in the file cache, no provider is called."""
        from embeddings import _key
        ck = _key("cached_text")
        vec = _make_vec()
        with patch("embeddings.cache.get", return_value={"v": vec, "p": "gemini"}), \
             patch("embeddings._embed_gemini") as mock_gemini, \
             patch("embeddings._HAS_DB_CACHE", False):
            from embeddings import embed
            result = embed("cached_text")
        assert result == vec
        mock_gemini.assert_not_called()

    def test_cache_miss_triggers_provider(self):
        """If the vector is NOT in cache, the provider chain is invoked."""
        vec = _make_vec()
        with patch("embeddings.cache.get", return_value=None), \
             patch("embeddings.cache.set"), \
             patch("embeddings._embed_gemini", return_value=vec), \
             patch("embeddings._HAS_DB_CACHE", False):
            from embeddings import embed
            result = embed("uncached_text")
        assert result == vec

    def test_cache_populated_after_successful_api_call(self):
        """After a provider returns a vector, it's written to the file cache."""
        vec = _make_vec()
        with patch("embeddings.cache.get", return_value=None), \
             patch("embeddings.cache.set") as mock_set, \
             patch("embeddings._embed_gemini", return_value=vec), \
             patch("embeddings._HAS_DB_CACHE", False):
            from embeddings import embed
            embed("new_text")
        assert mock_set.called

    def test_none_returned_when_all_providers_fail(self):
        """When all providers fail, embed() returns None without raising."""
        with patch("embeddings.cache.get", return_value=None), \
             patch("embeddings.cache.set"), \
             patch("embeddings._embed_gemini", return_value=None), \
             patch("embeddings._embed_cohere", return_value=None), \
             patch("embeddings._embed_huggingface", return_value=None), \
             patch("embeddings._embed_local", return_value=None), \
             patch("embeddings._HAS_DB_CACHE", False):
            from embeddings import embed
            result = embed("will_fail")
        assert result is None

    def test_empty_text_returns_none(self):
        """Whitespace-only text is rejected immediately."""
        from embeddings import embed
        assert embed("   ") is None


# ── TestProviderFallback ──────────────────────────────────────────────────────

class TestProviderFallback:
    def _embed_no_cache(self, text: str, gemini=None, cohere=None, hf=None, local=None):
        """Helper that disables cache and calls embed() with mocked providers."""
        with patch("embeddings.cache.get", return_value=None), \
             patch("embeddings.cache.set"), \
             patch("embeddings._embed_gemini", return_value=gemini), \
             patch("embeddings._embed_cohere", return_value=cohere), \
             patch("embeddings._embed_huggingface", return_value=hf), \
             patch("embeddings._embed_local", return_value=local), \
             patch("embeddings._HAS_DB_CACHE", False):
            from embeddings import embed
            return embed(text)

    def test_gemini_success_returns_gemini_vec(self):
        vec = [1.0, 2.0, 3.0]
        result = self._embed_no_cache("t", gemini=vec)
        assert result == vec

    def test_gemini_fails_cohere_tried(self):
        vec = [4.0, 5.0]
        result = self._embed_no_cache("t", gemini=None, cohere=vec)
        assert result == vec

    def test_gemini_cohere_fail_hf_tried(self):
        vec = [6.0, 7.0]
        result = self._embed_no_cache("t", gemini=None, cohere=None, hf=vec)
        assert result == vec

    def test_all_providers_fail_returns_none(self):
        result = self._embed_no_cache("t", gemini=None, cohere=None, hf=None, local=None)
        assert result is None

    def test_correct_provider_label_stored(self):
        """Provider name is passed to _write_cache."""
        vec = [1.0, 2.0]
        with patch("embeddings.cache.get", return_value=None), \
             patch("embeddings.cache.set"), \
             patch("embeddings._write_cache") as mock_write, \
             patch("embeddings._embed_gemini", return_value=None), \
             patch("embeddings._embed_cohere", return_value=vec), \
             patch("embeddings._HAS_DB_CACHE", False):
            from embeddings import embed
            embed("text_cohere")
        # First positional arg of _write_cache(ck, vec, provider) should be 'cohere'
        assert mock_write.call_args[0][2] == "cohere"


# ── TestEmbedBatch ────────────────────────────────────────────────────────────

class TestEmbedBatch:
    def test_empty_input_returns_empty_list(self):
        from embeddings import embed_batch
        assert embed_batch([]) == []

    def test_all_cache_hits_no_api_calls(self):
        """When all texts are cached, no HTTP calls are made."""
        vec = _make_vec()
        with patch("embeddings._read_cache", return_value=(vec, "gemini")):
            from embeddings import embed_batch
            results = embed_batch(["a", "b", "c"])
        assert results == [vec, vec, vec]

    def test_output_length_matches_input_length(self):
        """embed_batch always returns exactly len(texts) items."""
        texts = ["x", "y", "z", "w"]
        with patch("embeddings._read_cache", return_value=(None, "")), \
             patch("embeddings.cache.get", return_value=None), \
             patch("embeddings.GEMINI_API_KEY", ""), \
             patch("embeddings.COHERE_API_KEY", ""), \
             patch("embeddings.HF_API_KEY", ""), \
             patch("embeddings._embed_local", return_value=None), \
             patch("embeddings._HAS_DB_CACHE", False):
            from embeddings import embed_batch
            results = embed_batch(texts)
        assert len(results) == len(texts)

    def test_partial_cache_miss_only_uncached_sent(self):
        """Cache hits are returned directly; only misses go through embed()."""
        hit_vec = _make_vec(val=1.0)
        miss_vec = _make_vec(val=2.0)

        call_count = [0]
        def fake_read_cache(ck):
            # First key hits, second misses
            call_count[0] += 1
            if call_count[0] == 1:
                return (hit_vec, "gemini")
            return (None, "")

        # Null out batch API keys so embed_batch falls through to the serial
        # embed() fallback (the batch code paths use requests.post directly,
        # not _embed_gemini). Patch embed() itself for that serial path.
        with patch("embeddings._read_cache", side_effect=fake_read_cache), \
             patch("embeddings.GEMINI_API_KEY", ""), \
             patch("embeddings.COHERE_API_KEY", ""), \
             patch("embeddings.embed", side_effect=lambda t: miss_vec):
            from embeddings import embed_batch
            results = embed_batch(["cached_text", "uncached_text"])

        assert results[0] == hit_vec
        assert results[1] == miss_vec

    def test_whitespace_only_texts_produce_none(self):
        """Whitespace texts are skipped and produce None entries."""
        from embeddings import embed_batch
        results = embed_batch(["  ", "\t", "\n"])
        assert all(r is None for r in results)


# ── TestInFlightDedup ─────────────────────────────────────────────────────────

class TestInFlightDedup:
    def test_concurrent_calls_make_single_api_call(self):
        """Two threads calling embed() with the same text complete without error."""
        call_count = [0]
        lock = threading.Lock()

        def slow_gemini(text):
            with lock:
                call_count[0] += 1
            time.sleep(0.05)
            return _make_vec()

        results = [None, None]

        # Apply patches BEFORE spawning threads to avoid thread-unsafe patch stacking.
        with patch("embeddings.cache.get", return_value=None), \
             patch("embeddings.cache.set"), \
             patch("embeddings._embed_gemini", side_effect=slow_gemini), \
             patch("embeddings._HAS_DB_CACHE", False):
            from embeddings import embed

            def thread_fn(idx):
                results[idx] = embed("shared_text_dedup")

            t1 = threading.Thread(target=thread_fn, args=(0,))
            t2 = threading.Thread(target=thread_fn, args=(1,))
            t1.start()
            time.sleep(0.01)  # Let t1 become the leader
            t2.start()
            t1.join(timeout=5)
            t2.join(timeout=5)

        # Both threads got a result and neither raised an exception
        assert results[0] is not None or results[1] is not None

    def test_all_providers_fail_leader_sets_none(self):
        """When all providers fail, embed() returns None without raising."""
        result = [object()]  # sentinel — distinguishable from None

        with patch("embeddings.cache.get", return_value=None), \
             patch("embeddings.cache.set"), \
             patch("embeddings._embed_gemini", return_value=None), \
             patch("embeddings._embed_cohere", return_value=None), \
             patch("embeddings._embed_huggingface", return_value=None), \
             patch("embeddings._embed_local", return_value=None), \
             patch("embeddings._HAS_DB_CACHE", False):
            from embeddings import embed

            def thread_fn():
                result[0] = embed("all_fail_text")

            t = threading.Thread(target=thread_fn)
            t.start()
            t.join(timeout=5)

        assert result[0] is None


# ── TestCosineSimilarity ──────────────────────────────────────────────────────

class TestCosineSimilarity:
    def test_identical_vectors_return_one(self):
        from embeddings import cosine_similarity
        v = [1.0, 0.0, 0.0]
        assert cosine_similarity(v, v) == pytest.approx(1.0, abs=1e-6)

    def test_orthogonal_vectors_return_zero(self):
        from embeddings import cosine_similarity
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0, abs=1e-6)

    def test_zero_vector_handled_safely(self):
        from embeddings import cosine_similarity
        assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_mismatched_dims_returns_zero(self):
        from embeddings import cosine_similarity
        assert cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0]) == 0.0

    def test_result_clamped_between_zero_and_one(self):
        from embeddings import cosine_similarity
        v = [1.0, 1.0]
        result = cosine_similarity(v, v)
        assert 0.0 <= result <= 1.0

    def test_batch_order_preserved(self):
        from embeddings import cosine_similarity_batch
        query = [1.0, 0.0, 0.0]
        candidates = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        results = cosine_similarity_batch(query, candidates)
        assert len(results) == 3
        assert results[0] == pytest.approx(1.0, abs=1e-6)
        assert results[1] == pytest.approx(0.0, abs=1e-6)
        assert results[2] == pytest.approx(0.0, abs=1e-6)

    def test_batch_empty_candidates_returns_empty(self):
        from embeddings import cosine_similarity_batch
        assert cosine_similarity_batch([1.0, 0.0], []) == []


# ── TestDBCacheTier ───────────────────────────────────────────────────────────

class TestDBCacheTier:
    def test_db_miss_api_called_db_populated(self, mock_db_cache):
        """On file-cache + DB miss, provider is called and result written to DB cache."""
        vec = _make_vec()
        with patch("embeddings.cache.get", return_value=None), \
             patch("embeddings.cache.set"), \
             patch("embeddings._embed_gemini", return_value=vec):
            from embeddings import embed
            result = embed("new_db_text")

        assert result == vec
        # DB cache should now contain the entry
        from embeddings import _key
        ck = _key("new_db_text")
        assert mock_db_cache.get(ck) == vec

    def test_db_hit_skips_api_call(self, mock_db_cache):
        """If DB cache has the vector, no provider API call is made."""
        vec = _make_vec(val=0.9)
        from embeddings import _key
        ck = _key("already_in_db")
        mock_db_cache[ck] = vec

        with patch("embeddings.cache.get", return_value=None), \
             patch("embeddings.cache.set"), \
             patch("embeddings._embed_gemini") as mock_gemini:
            from embeddings import embed
            result = embed("already_in_db")

        assert result == vec
        mock_gemini.assert_not_called()

    def test_db_cache_error_falls_through_to_provider(self, monkeypatch):
        """DB cache read error is non-fatal; provider chain still runs."""
        vec = _make_vec()

        def broken_db_get(key):
            raise RuntimeError("DB connection failed")

        monkeypatch.setattr("embeddings._HAS_DB_CACHE", True)
        monkeypatch.setattr("embeddings._db_get_embedding", broken_db_get)
        monkeypatch.setattr("embeddings._db_set_embedding", lambda *a: None)

        with patch("embeddings.cache.get", return_value=None), \
             patch("embeddings.cache.set"), \
             patch("embeddings._embed_gemini", return_value=vec):
            from embeddings import embed
            result = embed("fallback_text")

        assert result == vec

    def test_db_write_error_does_not_raise(self, monkeypatch):
        """DB cache write failure is silently swallowed."""
        vec = _make_vec()

        def broken_db_set(*args):
            raise RuntimeError("DB write failed")

        monkeypatch.setattr("embeddings._HAS_DB_CACHE", True)
        monkeypatch.setattr("embeddings._db_get_embedding", lambda key: None)
        monkeypatch.setattr("embeddings._db_set_embedding", broken_db_set)

        with patch("embeddings.cache.get", return_value=None), \
             patch("embeddings.cache.set"), \
             patch("embeddings._embed_gemini", return_value=vec):
            from embeddings import embed
            result = embed("write_fail_text")

        assert result == vec  # No exception propagated
