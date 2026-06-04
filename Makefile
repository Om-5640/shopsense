.PHONY: eval test ci install validate-pools

# Run golden-file LLM output + shape tests (no API keys needed, ~1s)
eval:
	python -m pytest tests/evals/ -v

# Validate every benchmark pool: schema, referential integrity, and that each
# scenario's expected_rank_1 matches the deterministic engine winner.
validate-pools:
	python -m evals.benchmarks.validate_pools

# Run full test suite: unit + integration + e2e + smoke tests
test:
	python -m pytest tests/ evals/integration/ -q

# CI gate: pool integrity + full tests + intelligence eval regression check
ci:
	python -m evals.benchmarks.validate_pools && python -m pytest tests/ evals/integration/ -q && python -m evals ci

# Install all Python dependencies
install:
	pip install -r api/requirements.txt
