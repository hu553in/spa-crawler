SHELL := /bin/bash
.ONESHELL:
.SHELLFLAGS := -euo pipefail -c

.PHONY: ensure_env
ensure_env:
	if [ ! -f .env ]; then cp .env.example .env; fi

.PHONY: install_deps
install_deps:
	uv sync --frozen --no-install-project

.PHONY: sync_deps
sync_deps:
	uv sync

.PHONY: check_deps_updates
check_deps_updates:
	uv tree --outdated --depth=1 | grep latest

.PHONY: check_deps_vuln
check_deps_vuln:
	uv run pysentry-rs .

.PHONY: lint
lint:
	uv run ruff format
	uv run ruff check --fix

.PHONY: test
test:
	uv run pytest

.PHONY: check_types
check_types:
	uv run ty check .

.PHONY: check
check:
	uv run prek --all-files --hook-stage pre-commit

# Project-specific

.PHONY: help
help:
	uv run python -m spa_crawler --help

.PHONY: crawl
crawl: ensure_env
	uv run --env-file .env python -m spa_crawler

.PHONY: start_spa
start_spa: ensure_env
	docker compose -f docker-compose.spa.yml up -d --build

.PHONY: stop_spa
stop_spa: ensure_env
	docker compose -f docker-compose.spa.yml down

.PHONY: restart_spa
restart_spa: stop_spa start_spa

.PHONY: all
all: stop_spa clean install_deps crawl start_spa

.PHONY: clean
clean:
	rm -rf storage
	rm -rf out
