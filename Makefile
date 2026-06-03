.PHONY: eval test ci install

# Run golden-file LLM output tests (no API keys needed, ~1s)
eval:
	python -m pytest tests/evals/ -v

# Run full test suite: unit + integration + e2e + smoke tests
test:
	python -m pytest tests/ evals/integration/ -q

# CI gate: full tests + intelligence eval regression check
ci:
	python -m pytest tests/ evals/integration/ -q && python -m evals ci

# Install all Python dependencies
install:
	pip install -r api/requirements.txt
