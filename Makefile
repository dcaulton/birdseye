.PHONY: install dev lint format test db-upgrade db-downgrade

install:
	uv sync

dev:
	uv run uvicorn src.birdseye.main:app --reload --port 8001

lint:
	uv run ruff check src tests
	uv run mypy src

format:
	uv run ruff format src tests

test:
	uv run pytest

db-upgrade:
	uv run alembic upgrade head

db-downgrade:
	uv run alembic downgrade -1
