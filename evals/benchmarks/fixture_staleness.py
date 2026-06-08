"""
Fixture Staleness Benchmark.

Tracks freshness and integrity of every benchmark data file in the eval platform:
  - Recorded pipeline fixtures  (evals/data/fixtures/recorded/*.json) — threshold 90 days
  - Pool data files             (evals/data/pools/*.json)              — threshold 365 days

Each data file should carry a ``_meta`` block with:
  ``captured_at``   — ISO datetime string with timezone (e.g. "2026-06-08T00:00:00+00:00")
  ``schema_version``— format version string (e.g. "1.0")
  ``content_hash``  — SHA-256 hex digest of canonical non-meta content

The content hash covers ONLY the data payload (not ``_meta`` itself) so the hash
can be stored inside the file without circular dependence:
  - Recorded fixtures: SHA-256 of json.dumps(scored_products, sort_keys=True)
  - Pool files:        SHA-256 of json.dumps({criteria, products}, sort_keys=True)

Staleness thresholds (configurable via STALENESS_THRESHOLDS):
  "recorded" — 90 days   (pipeline output captures reflect real LLM behaviour)
  "pool"     — 365 days  (hand-crafted benchmark data, updated less frequently)

Public API:
  ``compute_content_hash(path, fixture_type)`` → sha256 hex string or ""
  ``load_all_fixture_records()``               → list[FixtureRecord]
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_EVALS_DIR = Path(__file__).resolve().parent.parent  # evals/
_REPO_ROOT = _EVALS_DIR.parent                       # repo root

_RECORDED_DIR = _EVALS_DIR / "data" / "fixtures" / "recorded"
_POOLS_DIR = _EVALS_DIR / "data" / "pools"

# Staleness thresholds in days per fixture type.
STALENESS_THRESHOLDS: dict[str, int] = {
    "recorded": 90,
    "pool": 365,
}

_SCHEMA_VERSION = "1.0"


# ── FixtureRecord dataclass ───────────────────────────────────────────────────

@dataclass
class FixtureRecord:
    """
    Represents one benchmark data file (recorded fixture or pool).

    ``stored_hash``    — value of ``_meta.content_hash`` inside the file (may be "")
    ``computed_hash``  — SHA-256 computed live over the non-meta file content

    Use the ``has_timestamp``, ``is_fresh()``, and ``hash_intact`` properties
    to evaluate staleness / integrity for a given reference date.
    """
    fixture_id: str
    fixture_type: str              # "recorded" | "pool"
    path: str                      # relative to repo root (display only)
    captured_at: str               # ISO datetime with TZ from _meta, or ""
    schema_version: str            # from _meta, or ""
    stored_hash: str               # SHA-256 from _meta.content_hash, or ""
    computed_hash: str             # SHA-256 computed live from file
    staleness_threshold_days: int  # 90 for recorded, 365 for pool

    # ── timestamp checks ──────────────────────────────────────────────────────

    @property
    def has_timestamp(self) -> bool:
        """True if captured_at is a valid ISO datetime string WITH timezone info."""
        if not self.captured_at:
            return False
        try:
            dt = datetime.fromisoformat(self.captured_at)
            return dt.tzinfo is not None
        except (ValueError, TypeError):
            return False

    def _parsed_captured_at(self) -> datetime | None:
        if not self.has_timestamp:
            return None
        try:
            return datetime.fromisoformat(self.captured_at)
        except Exception:
            return None

    def age_days(self, reference: datetime | None = None) -> int | None:
        """
        Days between captured_at and reference (default: datetime.now(UTC)).
        Returns None if captured_at is missing or unparseable.
        Future timestamps clamp to 0 (not negative).
        """
        dt = self._parsed_captured_at()
        if dt is None:
            return None
        ref = reference or datetime.now(timezone.utc)
        return max(0, (ref - dt).days)

    def is_fresh(self, reference: datetime | None = None) -> bool:
        """True if age_days is within staleness_threshold_days."""
        days = self.age_days(reference)
        return days is not None and days <= self.staleness_threshold_days

    # ── hash integrity ────────────────────────────────────────────────────────

    @property
    def hash_intact(self) -> bool:
        """True if both hashes are non-empty and identical."""
        return bool(self.stored_hash) and self.stored_hash == self.computed_hash


# ── Content hash computation ──────────────────────────────────────────────────

def compute_content_hash(path: Path, fixture_type: str) -> str:
    """
    Compute SHA-256 of the canonical non-meta content of a data file.

    Recorded fixtures: hash covers ``scored_products`` only.
    Pool files:        hash covers ``criteria`` + ``products`` only.

    ``_meta`` is explicitly excluded so the hash can be stored inside the file.
    Returns empty string if the file cannot be read or parsed.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if fixture_type == "recorded":
            payload = data.get("scored_products", [])
        else:  # pool
            payload = {
                "criteria": data.get("criteria", []),
                "products": data.get("products", []),
            }
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    except Exception:
        return ""


# ── Discovery ─────────────────────────────────────────────────────────────────

def load_all_fixture_records() -> list[FixtureRecord]:
    """
    Discover every benchmark data file and return a FixtureRecord for each.

    Discovery order:
      1. Recorded fixtures (evals/data/fixtures/recorded/*.json), sorted by name
      2. Pool files        (evals/data/pools/*.json), sorted by name

    Files whose stems start with "_" are skipped (e.g. _SCHEMA.md).
    """
    records: list[FixtureRecord] = []

    # ── Recorded fixtures ─────────────────────────────────────────────────────
    if _RECORDED_DIR.exists():
        for path in sorted(_RECORDED_DIR.glob("*.json")):
            if path.stem.startswith("_"):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            meta = data.get("_meta", {}) if isinstance(data, dict) else {}
            computed = compute_content_hash(path, "recorded")
            try:
                rel = str(path.relative_to(_REPO_ROOT))
            except ValueError:
                rel = path.name
            records.append(FixtureRecord(
                fixture_id=path.stem,
                fixture_type="recorded",
                path=rel,
                captured_at=meta.get("captured_at", ""),
                schema_version=meta.get("schema_version", ""),
                stored_hash=meta.get("content_hash", ""),
                computed_hash=computed,
                staleness_threshold_days=STALENESS_THRESHOLDS["recorded"],
            ))

    # ── Pool files ────────────────────────────────────────────────────────────
    if _POOLS_DIR.exists():
        for path in sorted(_POOLS_DIR.glob("*.json")):
            if path.stem.startswith("_"):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            meta = data.get("_meta", {}) if isinstance(data, dict) else {}
            computed = compute_content_hash(path, "pool")
            try:
                rel = str(path.relative_to(_REPO_ROOT))
            except ValueError:
                rel = path.name
            records.append(FixtureRecord(
                fixture_id=path.stem,
                fixture_type="pool",
                path=rel,
                captured_at=meta.get("captured_at", ""),
                schema_version=meta.get("schema_version", ""),
                stored_hash=meta.get("content_hash", ""),
                computed_hash=computed,
                staleness_threshold_days=STALENESS_THRESHOLDS["pool"],
            ))

    return records
