SHELL := /bin/bash
.ONESHELL:
.SHELLFLAGS := -euo pipefail -c

.PHONY: ensure-env
ensure-env:
	if [ ! -f .env ]; then cp .env.example .env; fi

.PHONY: install-deps
install-deps:
	uv sync --frozen --no-install-project

.PHONY: lint
lint:
	uv run ruff format
	uv run ruff check --fix

.PHONY: test
test:
	uv run pytest

.PHONY: check-types
check-types:
	uv run ty check .

.PHONY: check
check:
	uv run prek --all-files --hook-stage pre-commit

# Project-specific

.PHONY: help
help:
	uv run python -m spa_crawler --help

.PHONY: crawl
crawl: ensure-env
	uv run --env-file .env python -m spa_crawler

.PHONY: start-spa
start-spa: ensure-env
	docker compose -f docker-compose.spa.yml up -d --build

.PHONY: stop-spa
stop-spa: ensure-env
	docker compose -f docker-compose.spa.yml down

.PHONY: restart-spa
restart-spa: stop-spa start-spa

.PHONY: all
all: stop-spa clean install-deps crawl start-spa

.PHONY: clean
clean:
	rm -rf storage
	rm -rf out
