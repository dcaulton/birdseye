.PHONY: install docker-up docker-down migrate dev test lint format pre-commit-install clean

install:
	uv sync --dev

docker-up:
	docker compose up -d

docker-down:
	docker compose down

migrate:
	uv run alembic upgrade head

dev:
	uv run uvicorn src.birdseye.main:app --reload --port 8001

test:
	uv run pytest -q

lint:
	uv run ruff check .
	uv run mypy src

format:
	uv run ruff format .

pre-commit-install:
	pre-commit install

clean:
	rm -rf .venv uv.lock .pytest_cache .ruff_cache .mypy_cache
