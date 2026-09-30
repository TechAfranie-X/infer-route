PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: install dev test test-unit test-integration lint format docker-up docker-down load-test

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
	$(BIN)/ruff check app tests load_tests
	$(BIN)/ruff format --check app tests load_tests

format:
	$(BIN)/ruff format app tests load_tests
	$(BIN)/ruff check --fix app tests load_tests

docker-up:
	docker compose up --build

docker-down:
	docker compose down

INFERROUTE_SCENARIO ?= baseline

load-test:
	INFERROUTE_SCENARIO=$(INFERROUTE_SCENARIO) $(BIN)/locust -f load_tests/locustfile.py --host http://localhost:8000
