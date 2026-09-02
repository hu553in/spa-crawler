.DEFAULT_GOAL := check

SHELL := /bin/bash
.ONESHELL:
.SHELLFLAGS := -euo pipefail -c

PRETTIER := bunx prettier -u
ACTIONLINT := bunx github-actionlint
TAPLO := bunx @taplo/cli

.PHONY: ensure-env
ensure-env:
	if [ ! -f .env ]; then cp .env.example .env; fi

.PHONY: install-deps
install-deps:
	uv sync --all-groups --locked

.PHONY: lint
lint:
	$(PRETTIER) -c .
	$(TAPLO) fmt --check
	uv run ruff check
	uv run ruff format --check

.PHONY: lint-fix
lint-fix:
	$(PRETTIER) -w .
	$(TAPLO) fmt
	uv run ruff check --fix
	uv run ruff format

.PHONY: test
test:
	uv run pytest

.PHONY: check-types
check-types:
	uv run ty check .

.PHONY: check-deps
check-deps:
	uv run deptry .

.PHONY: check-vulns
check-vulns:
	uv run pysentry-rs .

.PHONY: check-unused
check-unused:
	uv run vulture

.PHONY: check-security
check-security:
	git ls-files --cached --others --exclude-standard -z -- '*.py' | xargs -0 uv run bandit -c pyproject.toml

.PHONY: check-config
check-config:
	docker compose config --quiet --no-interpolate --no-env-resolution
	@image=$$(awk '/^FROM caddy:.* AS caddy-runtime$$/{print $$2; exit}' Dockerfile.spa); \
		test -n "$$image"; \
		docker run --rm --network none --entrypoint /bin/sh \
			-e ENABLE_BASIC_AUTH=false \
			-e BASIC_AUTH_USER=check \
			-e 'BASIC_AUTH_PASSWORD_HASH=$$2a$$14$$4YbfeJZykhrkPU6.Q7XYE.6tdjDUwMuEBEK8aVM1frvtyQhiA22vG' \
			-v "$(CURDIR)/Caddyfile:/etc/caddy/Caddyfile:ro" \
			-v "/dev/null:/srv/redirects.caddy:ro" \
			"$$image" -ec \
			'caddy fmt --diff /etc/caddy/Caddyfile >/dev/null && caddy validate --config /etc/caddy/Caddyfile'

.PHONY: check-renovate
check-renovate:
	bunx --package renovate renovate-config-validator --strict --no-global renovate.json

.PHONY: check-hooks
check-hooks:
	uv run prek validate-config prek.toml

.PHONY: check-workflows
check-workflows:
	$(ACTIONLINT)

.PHONY: check
check: lint check-hooks check-types check-deps check-vulns check-unused check-security check-config check-renovate test check-workflows

.PHONY: check-fix
check-fix: lint-fix
	$(MAKE) check

# Project-specific

.PHONY: help
help:
	uv run python3 -m spa_crawler --help

.PHONY: crawl
crawl: ensure-env
	uv run --env-file .env python3 -m spa_crawler

.PHONY: start-spa
start-spa: ensure-env
	docker compose up -d --build --wait

.PHONY: stop-spa
stop-spa: ensure-env
	docker compose down

.PHONY: restart-spa
restart-spa: stop-spa start-spa

.PHONY: all
all: stop-spa clean install-deps crawl start-spa

.PHONY: clean
clean:
	rm -rf storage
	rm -rf out
	mkdir -p out
	touch out/.gitkeep
