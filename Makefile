SHELL := /bin/bash
.ONESHELL:
.SHELLFLAGS := -euo pipefail -c

.PHONY: ensure_env
ensure_env:
	if [ ! -f .env ]; then cp .env.example .env; fi

.PHONY: all
all: stop clean install_deps crawl start

.PHONY: clean
clean:
	rm -rf storage
	rm -rf out

.PHONY: install_deps
install_deps:
	uv sync

.PHONY: sync_deps
sync_deps:
	uv sync

.PHONY: check_deps_updates
check_deps_updates:
	uv tree --outdated --depth=1 | grep latest

.PHONY: check_deps_vuln
check_deps_vuln:
	.venv/bin/pysentry-rs --sources pypa,pypi,osv --fail-on low .

.PHONY: help
help:
	uv run python -m spa_crawler --help

.PHONY: crawl
crawl:
	uv run python -m spa_crawler

.PHONY: start
start: ensure_env
	docker compose up -d --build

.PHONY: stop
stop: ensure_env
	docker compose down

.PHONY: restart
restart: stop start

.PHONY: lint
lint:
	.venv/bin/ruff format
	.venv/bin/ruff check --fix

.PHONY: check_types
check_types:
	.venv/bin/ty check .

.PHONY: check
check:
	.venv/bin/prek --all-files --hook-stage pre-commit
