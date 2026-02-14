# SPA crawler

[![CI](https://github.com/hu553in/spa-crawler/actions/workflows/ci.yml/badge.svg)](https://github.com/hu553in/spa-crawler/actions/workflows/ci.yml)

- [License](./LICENSE)
- [How to contribute](./CONTRIBUTING.md)
- [Code of conduct](./CODE_OF_CONDUCT.md)

A CLI-friendly crawler that can **optionally log in**, **crawl a website**, and **mirror pages and static assets**
into a local directory so the result can be served by a static web server (Caddy, Nginx, etc.).

The project targets modern SPAs and Next.js-style applications where content is rendered dynamically and
traditional tools like `wget` or `curl` often fail to capture working pages.

---

## Features

- Optional authentication flow
  - Fills login/password inputs
  - Submits the form
  - Waits for redirect after successful login

- Playwright-based rendering
  - Supports SPAs, hydration, and client-side routing
  - Handles dynamic content loading

- Mirrors HTML pages
  - Saved to `out/pages/**/index.html`

- Mirrors many static assets
  - Examples: `/_next/**`, `*.css`, `*.js`, images, fonts, etc.
  - Saved to `out/assets/**` and `out/assets_q/**`

- Single browser session / session pool
  - Designed to improve reliability for authenticated crawling

- Additional URL discovery
  - Extracts candidate links from rendered DOM
  - Reads Next.js `__NEXT_DATA__` from the page
  - Reads `/_next/data/**.json` payloads from intercepted responses
  - Helps discover routes referenced in JSON/JS, not only in `<a>` tags

---

## Output structure

```
out/
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

- `out/pages` → HTML root
- `out/pages_q` → query HTML variants (e.g. `/search?page=2`)
- `out/assets` → static files root (or mounted under `/`, depending on server configuration)
- `out/assets_q` → query static variants (e.g. `/app.js?v=123`)

---

## Install

1. Install [uv](https://docs.astral.sh/uv/)
2. Install dependencies:
   ```
   make install_deps
   ```

---

## Usage

The crawler is implemented as:

- async Python function `crawl(config)`
- Typer CLI wrapper

Basic flow:

```
make help
```

Then review:

- `Makefile`
- `Dockerfile`
- `docker-compose.yml`
- `Caddyfile`

for real usage examples and deployment templates.

---

## Deployment of mirrored site

This project only produces a mirrored static copy of a website.
You must decide how and where to deploy or serve it.

Example deployment stack included:

- `Dockerfile`
- `docker-compose.yml`
- `Caddyfile`
- environment configuration via `.env`

To use HTTP basic authentication with Caddy, generate a password hash:

```
caddy hash-password
```

Then set environment variables used by `Caddyfile`:

- `ENABLE_BASIC_AUTH=true`
- `BASIC_AUTH_USER=<username>`
- `BASIC_AUTH_PASSWORD_HASH=<output from previous command>`

---

## Limitations

This is a hobby / experimental project.
It aims to handle modern SPAs reasonably well but is **not a fully robust site mirroring solution**.

### Session configuration

Session behavior is currently hardcoded.
There are no CLI arguments to tune session pool settings or advanced browser session parameters.

Authenticated crawling may require manual code adjustments.

---

### High parallelism and memory usage

At high concurrency levels the crawler may:

- consume large amounts of RAM
- trigger repeated warnings about memory limits
- become unstable or slower

Recommended approach:

- Use low concurrency
- For authenticated crawling use concurrency = 1

### Hardware tuning

You can tune Crawlee memory behavior via environment variables:

- `CRAWLEE_MEMORY_MBYTES`: absolute memory limit (in MB) used by Crawlee autoscaling
- `CRAWLEE_MAX_USED_MEMORY_RATIO`: fraction of that limit that can be used before throttling

Example `.env` values:

```
CRAWLEE_MEMORY_MBYTES=20000
CRAWLEE_MAX_USED_MEMORY_RATIO=0.95
```

Tuning guidance:

- lower values can reduce OOM risk on smaller machines
- higher values can improve throughput on larger machines, but may increase RAM pressure

---

### Large number of HTTP errors in output

During crawling you may see large amounts of:

- 404 responses
- failed asset requests
- transient navigation errors

This is expected behavior for modern SPAs and does not necessarily indicate crawler failure.

The crawler intentionally prioritizes successful page mirroring rather than eliminating every failed request.

---

### Not all assets can be mirrored

The crawler downloads many static assets but **cannot guarantee full asset capture**.

Some resources may be skipped due to:

- streaming or opaque responses
- dynamically generated URLs
- authentication-protected resources
- browser caching behavior
- implementation complexity
- unsafe or ambiguous query strings for static-server mapping

The mirrored site may occasionally require manual fixes.

---

### URL discovery is heuristic

The crawler attempts to discover routes using:

- DOM extraction
- `__NEXT_DATA__` parsing
- `/_next/data/**.json` parsing

However, if a route is only accessible via complex client logic or hidden interactions,
it may never be discovered automatically.

Manual entrypoints may be required.

---

### Stability vs. completeness tradeoff

The project intentionally favors:

- simplicity
- maintainability
- ease of experimentation

over:

- perfect site replication
- exhaustive browser instrumentation

---

## Tips / troubleshooting

### SPA login inputs reset while typing

Some SPAs rerender login forms during hydration.

Increase rerender timeout to allow DOM stabilization.

---

### Pages exist but never get crawled

Common causes:

- routes exposed only via buttons or JS logic
- routes hidden in JSON menus
- conditional client routing

Possible fixes:

- add include globs/regexes
- add manual entrypoints via `--additional-crawl-entrypoint-url`
- extend URL extraction logic for project-specific patterns

---

### Assets missing / CSS not loading

Assets are mirrored using Playwright request interception.

Some resource types cannot be reliably captured and will be skipped.

---

### Unexpected logout or broken authentication

Recommended configuration:

- concurrency = 1
- single session pool
- no session rotation

---

## Development status

This project is:

- experimental
- evolving
- intentionally pragmatic rather than complete

It is useful for:

- offline mirrors
- testing mirrored SPAs
- migration experiments
- static hosting tests

It is **not** intended as a universal or production-grade website archiving solution.

---

## Ethics and legality

Only crawl content you are authorized to access and store.

Respect:

- website Terms of Service
- privacy rules
- copyright and licensing restrictions

Do not use this tool to extract or redistribute restricted data without permission.
