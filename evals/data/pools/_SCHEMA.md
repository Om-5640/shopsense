# Benchmark Pool Schema

Each `<category>.json` in this directory is an independent, self-contained benchmark
suite. Drop a new file here and the eval platform discovers it automatically — no code
change needed. Files starting with `_` (like this one) are ignored by the loader.

## Top-level keys

| key               | required | description |
|-------------------|----------|-------------|
| `category`        | yes      | Short category id, e.g. `"laptops"`. Becomes a scenario tag + phase label. |
| `description`     | no       | Human description of the pool. |
| `criteria`        | yes      | List of `{name, label}` — the scoring dimensions for this category. |
| `products`        | yes      | ≥2 products with per-criterion scores (0–10). |
| `scenarios`       | no       | Offline ranking scenarios (drive recommendation/ranking/personalization metrics). |
| `human_judgments` | no       | Expert-annotated rankings (drive the human-alignment metric). |

## Product

```json
{
  "name": "ProBook P8",
  "scores": { "performance": 10, "battery_life": 9 },   // keys MUST be declared criteria; 0–10
  "signal_strength": "strong",                          // strong|moderate|weak (optional)
  "mention_count": 82, "positive_mentions": 70, "negative_mentions": 12,  // optional
  "praise": ["fast", "great display"],                  // optional
  "complaints": [ {"text": "expensive", "confidence": "high"} ]           // optional
}
```

## Scenario

```json
{
  "id": "video_editor",
  "name": "Professional Video Editor",
  "tags": ["creative"],
  "weights": { "performance": 10, "display_quality": 9 },  // keys MUST be declared criteria
  "expected_rank_1": "ProBook P8",                          // MUST be a real product
  "expected_rank_1_not": ["BudgetBook L3"],                 // optional
  "expected_top_2": []                                      // optional
}
```

`expected_rank_1` is the ground-truth winner under `weights`. The pool validator
(`python -m evals.benchmarks.validate_pools`) recomputes the deterministic winner from
the scoring engine and fails if it disagrees — so a mislabeled scenario is caught before CI.

## Human judgment

```json
{
  "id": "hj_video_editor",
  "name": "Expert — Video Editor",
  "query": "best laptop for video editing",
  "expert_rank_1": "ProBook P8",
  "expert_rank_2": "GameRig G7",
  "expert_rank_3": "UltraSlim U4",
  "expert_rationale": "...",
  "weights": { "performance": 10 },
  "key_tradeoffs": ["..."]
}
```

## Authoring a new category

1. Copy an existing pool, change `category`, `criteria`, `products`.
2. Write scenarios; set each `expected_rank_1` to whichever product you believe should win.
3. Run `python -m evals.benchmarks.validate_pools` — it tells you any scenario whose
   labeled winner doesn't match the engine math, and any referential-integrity errors.
4. Commit. CI picks it up automatically.
