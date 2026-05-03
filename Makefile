.PHONY: install test test-full lint doctor

install:
	uv venv --python 3.12
	uv pip install -e ".[dev]"

test:
	uv run pytest -x -q tests/

test-full:
	uv run pytest -v --tb=short tests/

lint:
	uv run ruff check .
	uv run mypy basicctrl/

doctor:
	uv run python scripts/doctor.py
