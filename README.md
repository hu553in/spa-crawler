# SPA crawler

[![CI](https://github.com/hu553in/spa-crawler/actions/workflows/ci.yml/badge.svg)](https://github.com/hu553in/spa-crawler/actions/workflows/ci.yml)

CLI crawler for mirroring modern SPAs and Next.js-style sites into static files.

## What it does

- Optionally logs in through a browser form
- Crawls rendered pages with Playwright/Crawlee
- Saves HTML pages to `out/pages/**/index.html`
- Mirrors same-origin assets to `out/assets/**`
- Stores query-based page and asset variants in `out/pages_q/**` and `out/assets_q/**`
- Discovers links from DOM, Next.js data, intercepted responses, and configured entrypoints
- Exports observed redirects to `out/redirects.caddy`

## Requirements

- Python 3.14+
- `uv`
- Playwright-compatible browser dependencies
- Docker for published crawler images and the static-serving stack

## Setup

```bash
make install-deps
uv run playwright install chromium
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

Local help:

```bash
make help
```

Local crawl with `.env`:

```bash
make crawl
```

Published crawler image:

```bash
docker run --rm \
  -v "$(pwd)/out:/app/out" \
  ghcr.io/hu553in/spa-crawler:latest \
  --base-url https://example.com \
  --no-login-required
```

For authenticated crawls, pass `SPA_CRAWLER_LOGIN` and `SPA_CRAWLER_PASSWORD` as environment
variables. The image supports only headless mode.

## Output

```text
out/
  redirects.caddy
  pages/
  pages_q/
  assets/
  assets_q/
```

Serving layout:

- `out/pages` - HTML root
- `out/pages_q` - query HTML variants
- `out/assets` - static assets
- `out/assets_q` - query-based static variants
- `out/redirects.caddy` - generated Caddy redirects

Reset generated crawl state and output:

```bash
make clean
```

## Static serving

The included serving stack uses:

- `Dockerfile.spa`
- `docker-compose.spa.yml`
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
make install-deps
make check
```

Focused checks:

```bash
make lint
make test
make check-types
```
