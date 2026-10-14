.DEFAULT_GOAL := check

SHELL := /bin/bash -euo pipefail

PRETTIER := bunx prettier -u
ACTIONLINT := bunx github-actionlint
TAPLO := bunx @taplo/cli

.PHONY: install-deps
install-deps:
	uv sync --all-groups --locked

.PHONY: lint
lint:
	$(PRETTIER) -c .
	$(TAPLO) fmt --check
	uv run --locked ruff check
	uv run --locked ruff format --check

.PHONY: lint-fix
lint-fix:
	$(PRETTIER) -w .
	$(TAPLO) fmt
	uv run --locked ruff check --fix
	uv run --locked ruff format

.PHONY: check-hooks
check-hooks:
	uv run --locked prek validate-config prek.toml

.PHONY: check-types
check-types:
	uv run --locked ty check .

.PHONY: check-deps
check-deps:
	uv run --locked deptry .

.PHONY: check-vulns
check-vulns:
	uv run --locked pysentry-rs .

.PHONY: check-unused
check-unused:
	uv run --locked vulture

.PHONY: check-security
check-security:
	git ls-files --cached --others --exclude-standard -z -- '*.py' | xargs -0 uv run --locked bandit -c pyproject.toml

.PHONY: check-config
check-config:
	docker compose config --quiet --no-interpolate --no-env-resolution
	@image=$$(awk '/^FROM caddy:.* AS caddy-runtime$$/{print $$2; exit}' Dockerfile.spa); \
		test -n "$$image"; \
		env -u ENABLE_BASIC_AUTH -u BASIC_AUTH_USER -u BASIC_AUTH_PASSWORD_HASH \
			uv run --locked --env-file .env.example docker run --rm --network none --entrypoint /bin/sh \
			-e ENABLE_BASIC_AUTH \
			-e BASIC_AUTH_USER \
			-e BASIC_AUTH_PASSWORD_HASH \
			-v "$(CURDIR)/Caddyfile:/etc/caddy/Caddyfile:ro" \
			-v "/dev/null:/srv/redirects.caddy:ro" \
			"$$image" -ec \
			'caddy fmt --diff /etc/caddy/Caddyfile >/dev/null && caddy validate --config /etc/caddy/Caddyfile'

.PHONY: check-renovate
check-renovate:
	bunx --package renovate renovate-config-validator --strict --no-global renovate.json

.PHONY: test
test:
	uv run --locked pytest

.PHONY: check-workflows
check-workflows:
	$(ACTIONLINT)

.PHONY: check
check: lint check-hooks check-types check-deps check-vulns check-unused check-security check-config check-renovate test check-workflows

.PHONY: check-fix
check-fix: lint-fix
	$(MAKE) check

.PHONY: ensure-env
ensure-env:
	if [ ! -f .env ]; then cp .env.example .env; fi

# Project-specific

.PHONY: help
help:
	uv run --locked python3 -m spa_crawler --help

.PHONY: crawl
crawl: ensure-env
	uv run --locked --env-file .env python3 -m spa_crawler

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
