# SPA crawler

[![CI](https://github.com/hu553in/spa-crawler/actions/workflows/ci.yml/badge.svg)](https://github.com/hu553in/spa-crawler/actions/workflows/ci.yml)

- [License](./LICENSE)
- [Contributing](./CONTRIBUTING.md)
- [Code of conduct](./CODE_OF_CONDUCT.md)

A CLI-friendly crawler that can optionally authenticate, crawl a website, and mirror pages and static
assets into a local directory for static hosting.

The project targets modern SPAs and Next.js-style applications where content is rendered dynamically and
traditional tools like `wget` or `curl` often fail to capture complete pages.

## Features

- Optional authentication flow
  - Fills in login and password inputs
  - Submits the form
  - Waits for redirect after successful login

- Playwright-based rendering
  - Supports SPAs, hydration, and client-side routing
  - Handles dynamically loaded content

- Mirrors HTML pages
  - Saved to `out/pages/**/index.html`

- Static asset mirroring
  - Examples: `/_next/**`, `*.css`, `*.js`, images, and fonts
  - Mirrors same-origin non-HTML `document` payloads as assets
    when frameworks use them for data transport
  - Saved to `out/assets/**` and `out/assets_q/**`

- Single-session crawling
  - Uses a single browser session and session pool to improve reliability during authenticated crawling

- Additional URL discovery
  - Extracts candidate links from the rendered DOM
  - Reads Next.js `__NEXT_DATA__` from the page
  - Parses `/_next/data/**.json` payloads from intercepted responses
  - Helps discover routes referenced in JSON and JavaScript, not only in `<a>` tags

- Redirect behavior capture (hybrid)
  - Collects HTTP redirect edges from observed 3xx chains
  - Captures client-side redirects when the loaded URL changes in the browser
  - Exports high-confidence Caddy redirect rules to `out/redirects.caddy`
  - Creates HTML redirect pages for missing source pages as a static-hosting fallback

## Output structure

```text
out/
  redirects.caddy
  pages/
    index.html
    nested_page/index.html
    ...
  pages_q/
    search/
      page=2/index.html
    ...
  assets/
    _next/static/...
    logo.svg
    favicon.ico
    ...
  assets_q/
    _next/static/chunk.js/
      v=123
    ...
```

Typical serving layout:

- `out/pages` -> HTML root
- `out/pages_q` -> query HTML variants (e.g., `/search?page=2`)
- `out/assets` -> static files root (or mounted under `/`, depending on server configuration)
- `out/assets_q` -> query-based static variants (e.g., `/app.js?v=123`)
- `out/redirects.caddy` -> generated Caddy `redir` rules from observed redirects
- `out/pages` and `out/pages_q` may include generated HTML redirect pages for missing sources

## Installation

1. Install [uv](https://docs.astral.sh/uv/)
2. Install dependencies:
   ```bash
   make install-deps
   ```

## Usage

The crawler is implemented as:

- An async Python function `crawl(config)`
- A Typer CLI wrapper

Basic flow:

```bash
make help
```

Then review these files for practical usage examples and deployment templates:

- `Makefile`
- `Dockerfile.spa-crawler`
- `Dockerfile.spa`
- `docker-compose.spa.yml`
- `Caddyfile`

### Published crawler image

On every push to `main`, GitHub Actions publishes the crawler image to GHCR:

- `ghcr.io/hu553in/spa-crawler:latest`
- `ghcr.io/hu553in/spa-crawler:sha-<commit>`

Image build source:

- `Dockerfile.spa-crawler`

Pass crawler arguments at runtime. Mount `out/` so mirrored files remain on the host after the
container exits.

Minimal example:

```bash
docker run --rm \
  -v "$(pwd)/out:/app/out" \
  ghcr.io/hu553in/spa-crawler:latest \
  --base-url https://example.com \
  --no-login-required
```

Authenticated example:

```bash
docker run --rm \
  -v "$(pwd)/out:/app/out" \
  -e SPA_CRAWLER_LOGIN="$SPA_CRAWLER_LOGIN" \
  -e SPA_CRAWLER_PASSWORD="$SPA_CRAWLER_PASSWORD" \
  -e CRAWLEE_MEMORY_MBYTES=20000 \
  -e CRAWLEE_MAX_USED_MEMORY_RATIO=0.95 \
  ghcr.io/hu553in/spa-crawler:latest \
  --base-url https://example.com \
  --login-required \
  --login-path /login \
  --login-input-selector "input[name='login']:visible" \
  --password-input-selector "input[name='password']:visible"
```

Notes:

- `SPA_CRAWLER_LOGIN` and `SPA_CRAWLER_PASSWORD` are read from the environment.
- `--base-url` still has to be passed explicitly; otherwise Typer prompts for it.
- The published Docker image supports only headless mode. `--no-headless`
  is rejected in containers.
- Mounting `/app/out` is strongly recommended. Without it, crawl output stays only
  inside the container filesystem.
- `/app/storage` is declared as a volume for Crawlee runtime state. Mount it as well
  when the state needs to be inspected or persisted across runs.

## CLI filtering defaults

- Include links: `{base_url}/**` when no include filters are provided
- Exclude links: login regex only (`.*{login_path}.*`) when `--login-required` is set
- API path prefixes: empty by default; add `--api-path-prefix` values to exclude API routes
  from page discovery, asset mirroring, and redirect collection

## Deployment of mirrored site

The crawler produces a mirrored static copy of a website.
Deployment and serving are handled outside the crawler.

Included deployment stack:

- `Dockerfile.spa`
- `docker-compose.spa.yml`
- `Caddyfile`
- Environment configuration via `.env`

`Caddyfile` imports `/srv/redirects.caddy`.
`Dockerfile.spa` creates a no-op placeholder for this file when it is absent.
`Caddyfile` also normalizes methods other than `GET` or `HEAD` by redirecting them to `GET` with
`303` on the same URI (to avoid `405 Method Not Allowed` errors on static mirrors).

To use HTTP basic authentication with Caddy, generate a password hash:

```bash
caddy hash-password
```

Then set the environment variables used by `Caddyfile`:

- `ENABLE_BASIC_AUTH=true`
- `BASIC_AUTH_USER=<username>`
- `BASIC_AUTH_PASSWORD_HASH=<output from previous command>`

### Serving without Caddy

The repository ships only Caddy configuration. For other servers, reimplement the URL-to-filesystem
lookup and redirect rules from `Caddyfile` (page and asset lookup with and without query strings,
immutable cache for `/_next/*`, method normalization to `GET`).

## Limitations

- Session behavior is hardcoded (no CLI tuning). Authenticated crawling may need manual code adjustments.
- High concurrency can cause RAM pressure and instability. Use low concurrency; `concurrency = 1` for auth.
- Tune Crawlee memory via `CRAWLEE_MEMORY_MBYTES` and `CRAWLEE_MAX_USED_MEMORY_RATIO` env vars.
- Many 404s, failed asset requests, and transient errors during crawling are expected and normal for SPAs.
- Not all assets can be guaranteed captured (streaming responses, dynamic URLs, auth-protected resources).
- URL discovery is heuristic (DOM, `__NEXT_DATA__`, `/_next/data/**.json`). Hidden routes may be missed.
- Redirect export is observational: only redirects seen during crawl are exported.

## Tips and troubleshooting

### SPA login inputs reset while typing

Some SPAs rerender login forms during hydration.

Increase the rerender timeout to allow DOM stabilization.

### Pages exist but never get crawled

Common causes:

- Routes exposed only via buttons or JS logic
- Routes hidden in JSON menus
- Conditional client routing

Possible fixes:

- Add include globs or regexes
- Add manual entrypoints via `--additional-crawl-entrypoint-url`
- Extend URL extraction logic for project-specific patterns

### Assets missing or CSS not loading

Assets are mirrored using Playwright request interception.

Some resource types cannot be reliably captured and will be skipped.

HTML `document` responses are stored from DOM snapshots in `out/pages/**` instead of raw route
interception responses.

### Unexpected logout or broken authentication

Recommended configuration:

- `concurrency = 1`
- Single session pool
- No session rotation

## Ethics and legality

Only crawl content that is authorized for access and storage.

Respect:

- Website terms of service
- Privacy rules
- Copyright and licensing restrictions

Do not use this tool to extract or redistribute restricted data without permission.
