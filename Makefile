.PHONY: install test lint smoke run clean publish-dryrun publish

PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

install:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e ".[dev]"

test:
	$(BIN)/pytest tests/ -v

lint:
	$(BIN)/python -m compileall -q src/purr/
	$(BIN)/python -c "from purr.app import PurrApp; from purr import tools; print(f'OK {len(tools.TOOLS)} tools')"

smoke:
	PURR_HOME=/tmp/purr-smoke $(BIN)/python scripts/smoke_tools.py | head -80

run:
	$(BIN)/python -m purr

clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete

publish-dryrun:
	$(BIN)/pip install build
	$(BIN)/python -m build --sdist --wheel
	@echo "Built in dist/ — review before twine upload"

publish:
	$(BIN)/pip install twine build
	$(BIN)/python -m build --sdist --wheel
	$(BIN)/twine upload dist/*
