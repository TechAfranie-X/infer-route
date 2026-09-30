PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: install dev test test-unit test-integration lint format docker-up docker-down

install:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e ".[dev]"

dev:
	$(BIN)/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --no-access-log

test:
	$(BIN)/pytest

test-unit:
	$(BIN)/pytest tests/unit

test-integration:
	$(BIN)/pytest tests/integration

lint:
	$(BIN)/ruff check app tests
	$(BIN)/ruff format --check app tests

format:
	$(BIN)/ruff format app tests
	$(BIN)/ruff check --fix app tests

docker-up:
	docker compose up --build

docker-down:
	docker compose down
