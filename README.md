# SPA crawler

[![CI](https://github.com/hu553in/spa-crawler/actions/workflows/ci.yml/badge.svg)](https://github.com/hu553in/spa-crawler/actions/workflows/ci.yml)

CLI crawler for mirroring modern SPAs and Next.js-style sites into static files.

## What it does

- Optionally logs in through a browser form
- Crawls rendered pages with Playwright/Crawlee
- Saves HTML pages and same-origin assets, including query-based variants
- Discovers links from DOM, Next.js data, intercepted responses, and configured entrypoints
- Exports observed redirects for the bundled Caddy site

## Requirements

- Python 3.15 or newer
- `uv`
- Make and Bun for repository tooling
- Playwright-compatible browser dependencies
- Docker for published crawler images and the static-serving stack

## Setup

```bash
make ensure-env
uv run --locked --no-dev playwright install chromium
```

Published image:

```bash
docker pull ghcr.io/hu553in/spa-crawler:latest
```

`latest` follows `main`; `sha-*` tags identify commits. Pin
`ghcr.io/hu553in/spa-crawler@sha256:<digest>` for an immutable deployment.

Local image:

```bash
docker build -f Dockerfile.spa-crawler -t spa-crawler .
```

## Configuration

Run `make help` for all CLI options. Common inputs:

- `--base-url`
- `--login-required` / `--no-login-required`
- `--login-path`
- `--login-input-selector`
- `--password-input-selector`
- `--additional-crawl-entrypoint-url`
- `--api-path-prefix`

Environment variables used by the crawler or serving stack:

| Name                            | Purpose                                      |
| ------------------------------- | -------------------------------------------- |
| `SPA_CRAWLER_LOGIN`             | Login value used by authenticated crawls     |
| `SPA_CRAWLER_PASSWORD`          | Password value used by authenticated crawls  |
| `CRAWLEE_MEMORY_MBYTES`         | Crawlee memory budget                        |
| `CRAWLEE_MAX_USED_MEMORY_RATIO` | Crawlee memory pressure threshold            |
| `ENABLE_BASIC_AUTH`             | Enables basic auth in the bundled Caddy site |
| `BASIC_AUTH_USER`               | Caddy basic auth username                    |
| `BASIC_AUTH_PASSWORD_HASH`      | Caddy password hash                          |

Defaults:

- include links: `{base_url}/**`
- exclude links: login path regex when login is required
- API path prefixes: empty

## Usage

Run from a checkout:

```bash
make help
```

Crawl with `.env`:

```bash
make crawl
```

This prompts for the base URL and requires login by default. For a site without authentication:

```bash
uv run --locked --no-dev --env-file .env python3 -m spa_crawler --base-url https://example.com --no-login-required
```

Docker uses the [Playwright seccomp profile][playwright-seccomp] to run Chromium's sandbox as a
non-root user. Download the profile from Playwright v1.64.1:

```bash
curl -fsSLo playwright-seccomp.json \
  https://raw.githubusercontent.com/microsoft/playwright/v1.64.1/utils/docker/seccomp_profile.json
mkdir -p out
docker run --rm \
  --security-opt seccomp=playwright-seccomp.json \
  -v "$(pwd)/out:/app/out" \
  ghcr.io/hu553in/spa-crawler:latest \
  --base-url https://example.com \
  --no-login-required
```

On Linux, the bind-mounted `out` directory must be writable by the container's `app` user (UID
1000). For authenticated crawls, pass `SPA_CRAWLER_LOGIN` and `SPA_CRAWLER_PASSWORD` as environment
variables. The image supports only headless mode.

From a checkout, you can use `--security-opt seccomp=docker/playwright-seccomp.json` instead of
downloading the profile. Replace the published image name with `spa-crawler` to run the local image.

[playwright-seccomp]: https://playwright.dev/python/docs/docker#crawling-and-scraping

## Output

```text
out/
  redirects.caddy  # observed redirects
  pages/           # HTML pages (**/index.html)
  pages_q/         # query-based HTML variants
  assets/          # same-origin assets
  assets_q/        # query-based asset variants
```

Reset generated crawl state and output:

```bash
make clean
```

## Static serving

The included serving stack uses:

- `Dockerfile.spa`
- `compose.yaml`
- `Caddyfile`

Commands:

```bash
make start-spa
make stop-spa
make restart-spa
```

`Caddyfile` imports `/srv/redirects.caddy`, normalizes non-GET/HEAD methods with `303`, and maps
page, asset, and query-variant paths to the generated files.

## Limitations

- Crawling is heuristic; hidden routes can be missed
- Authenticated crawls should use low concurrency
- Some streaming, dynamic, or auth-protected assets cannot be captured reliably
- Redirect rules include only redirects observed during crawl
- Many transient 404s and failed asset requests are normal for SPAs

## Ethics and legality

Only crawl content that you are authorized to access, store, and redistribute.

## Development

```bash
bunx lefthook install
make check
```

Use `make check-fix` to apply supported fixes before the full check.

Focused checks:

```bash
make lint
make lint-fix
make check-hooks
make check-types
make check-deps
make check-vulns
make check-unused
make check-security
make check-config
make test
make check-workflows
```

`make check-config` validates the Compose stack and checks the bundled Caddyfile with
`.env.example`.
