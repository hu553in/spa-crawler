import json
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from html import escape
from http.client import BAD_REQUEST, MULTIPLE_CHOICES
from itertools import pairwise
from pathlib import Path
from typing import Any

from yarl import URL

from spa_crawler.url_discovery import looks_like_api_path
from spa_crawler.utils import (
    canonicalize_page_url,
    clean_absolute_http_url,
    safe_relative_path_for_page,
    safe_relative_path_for_query,
)


def _normalize_redirect_url(
    raw_url: str, base_url: URL, api_path_prefixes: Sequence[str]
) -> str | None:
    """Normalize a redirect URL and keep only crawlable same-origin page URLs."""
    try:
        u = clean_absolute_http_url(raw_url, drop_query=False)
    except ValueError:
        return None
    if u.origin() != base_url.origin():
        return None
    if looks_like_api_path(u.path or "/", api_path_prefixes):
        return None

    return str(canonicalize_page_url(u))


def _redirect_chain(final_request: Any) -> list[Any]:
    """Build a redirect chain from first request to final request."""
    chain = [final_request]
    prev = getattr(final_request, "redirected_from", None)
    while prev is not None:
        chain.append(prev)
        prev = getattr(prev, "redirected_from", None)
    chain.reverse()
    return chain


def _round_confidence(value: float) -> float:
    """Round confidence to a stable precision."""
    return round(value, 4)


@dataclass(frozen=True, slots=True)
class _RedirectCandidate:
    """A scored redirect observation ready for export selection."""

    source: str
    target: str
    status: int
    confidence: float
    seen: int
    kind_priority: int


def _relative_redirect_target(url: URL) -> str:
    """Render a same-origin URL as path+query for server/static redirects."""
    path = url.path or "/"
    if not path.startswith("/"):
        path = f"/{path}"
    if url.raw_query_string:
        return f"{path}?{url.raw_query_string}"
    return path


def _render_redirect_html(target_href: str) -> str:
    """Build a tiny HTML redirect document."""
    escaped_href = escape(target_href, quote=True)
    js_href = json.dumps(target_href)
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '  <meta charset="utf-8">',
            f'  <meta http-equiv="refresh" content="0; url={escaped_href}">',
            "  <title>Redirecting...</title>",
            f'  <link rel="canonical" href="{escaped_href}">',
            "  <script>",
            f"    window.location.replace({js_href});",
            "  </script>",
            "</head>",
            "<body>",
            f'  <p>Redirecting to <a href="{escaped_href}">{escaped_href}</a>.</p>',
            "</body>",
            "</html>",
            "",
        ]
    )


class RedirectCollector:
    """
    Collect redirect observations during crawling.

    Two sources are tracked:
      - HTTP redirects (3xx chain observed by Playwright).
      - Client-side redirects (URL changed after page loaded).
    """

    def __init__(
        self,
        base_url: URL,
        api_path_prefixes: Sequence[str],
        max_query_len_for_fs_mapping: int,
        default_server_redirect_status: int,
        max_confidence_for_not_export: float,
        min_redirect_chain_len: int,
    ) -> None:
        self._base_url = base_url
        self._api_path_prefixes = list(api_path_prefixes)
        self._max_query_len_for_fs_mapping = max_query_len_for_fs_mapping
        self._default_server_redirect_status = default_server_redirect_status
        self._max_confidence_for_not_export = max_confidence_for_not_export
        self._min_redirect_chain_len = min_redirect_chain_len
        self._http_targets: dict[str, Counter[str]] = defaultdict(Counter)
        self._http_statuses: dict[tuple[str, str], Counter[int]] = defaultdict(Counter)
        self._client_targets: dict[str, Counter[str]] = defaultdict(Counter)

    async def observe_http_redirects_from_response(self, response: Any) -> None:
        """Extract HTTP redirect edges from a Playwright navigation response."""
        request = getattr(response, "request", None)
        if request is None:
            return

        chain = _redirect_chain(request)
        if len(chain) < self._min_redirect_chain_len:
            return

        for source_req, target_req in pairwise(chain):
            source = _normalize_redirect_url(
                getattr(source_req, "url", ""), self._base_url, self._api_path_prefixes
            )
            target = _normalize_redirect_url(
                getattr(target_req, "url", ""), self._base_url, self._api_path_prefixes
            )
            if not source or not target or source == target:
                continue

            source_response = await source_req.response()
            if source_response is None:
                continue

            status = getattr(source_response, "status", None)
            if not isinstance(status, int) or status < MULTIPLE_CHOICES or status >= BAD_REQUEST:
                continue

            self._http_targets[source][target] += 1
            self._http_statuses[(source, target)][status] += 1

    def observe_client_redirect(self, source_url: str, target_url: str) -> None:
        """Record a client-side redirect from source URL to current page URL."""
        source = _normalize_redirect_url(source_url, self._base_url, self._api_path_prefixes)
        target = _normalize_redirect_url(target_url, self._base_url, self._api_path_prefixes)
        if not source or not target or source == target:
            return
        self._client_targets[source][target] += 1

    @staticmethod
    def _confidence(counter: Counter[str], target: str) -> float:
        """Return relative frequency for ``target`` within a source bucket."""
        total = sum(counter.values())
        if total <= 0:
            return 0.0
        return _round_confidence(counter[target] / total)

    @staticmethod
    def _primary_status(statuses: Counter[int]) -> int:
        """Pick the most frequent status, using the smallest code as a tie-breaker."""
        # Highest frequency first, then smallest status code for deterministic output.
        return sorted(statuses.items(), key=lambda item: (-item[1], item[0]))[0][0]

    def _redirect_candidates(self) -> list[_RedirectCandidate]:
        candidates: list[_RedirectCandidate] = []

        for source, targets in self._http_targets.items():
            for target, seen in targets.items():
                statuses = self._http_statuses[(source, target)]
                candidates.append(
                    _RedirectCandidate(
                        source=source,
                        target=target,
                        status=self._primary_status(statuses),
                        confidence=self._confidence(targets, target),
                        seen=seen,
                        kind_priority=2,  # HTTP redirect is more trustworthy than client-side.
                    )
                )

        for source, targets in self._client_targets.items():
            for target, seen in targets.items():
                candidates.append(
                    _RedirectCandidate(
                        source=source,
                        target=target,
                        status=self._default_server_redirect_status,
                        confidence=self._confidence(targets, target),
                        seen=seen,
                        kind_priority=1,
                    )
                )

        return candidates

    def _select_redirects_for_export(
        self, *, max_confidence_for_not_export: float | None = None
    ) -> list[_RedirectCandidate]:
        buckets: dict[str, list[_RedirectCandidate]] = defaultdict(list)
        if max_confidence_for_not_export is None:
            max_confidence_for_not_export = self._max_confidence_for_not_export

        for candidate in self._redirect_candidates():
            # Export only strict-majority candidates.
            if candidate.confidence <= max_confidence_for_not_export:
                continue
            buckets[candidate.source].append(candidate)

        selected: list[_RedirectCandidate] = []
        for source in sorted(buckets):
            # Deterministic tie-breaks keep output stable across runs.
            best = sorted(
                buckets[source],
                key=lambda c: (-c.confidence, -c.seen, -c.kind_priority, c.status, c.target),
            )[0]
            selected.append(best)

        return selected

    def write_server_redirect_rules(
        self, out_dir: Path, *, max_confidence_for_not_export: float | None = None
    ) -> Path:
        """Write Caddy redirect snippets based on best observed redirects."""
        if max_confidence_for_not_export is None:
            max_confidence_for_not_export = self._max_confidence_for_not_export

        selected = self._select_redirects_for_export(
            max_confidence_for_not_export=max_confidence_for_not_export
        )

        caddy_path = out_dir / "redirects.caddy"

        caddy_lines = [
            "# Auto-generated by spa-crawler from observed redirects.",
            "# Include this file from your Caddy config.",
        ]

        skipped_query_sources = 0
        written_rules = 0

        for candidate in selected:
            source = URL(candidate.source)
            target = URL(candidate.target)
            if source.raw_query_string:
                skipped_query_sources += 1
                continue

            source_path = source.path or "/"
            target_value = _relative_redirect_target(target)

            caddy_lines.append(f"redir {source_path} {target_value} {candidate.status}")
            written_rules += 1

        caddy_lines.extend(
            [
                f"# rules_written: {written_rules}",
                f"# skipped_query_sources: {skipped_query_sources}",
                "",
            ]
        )

        caddy_path.parent.mkdir(parents=True, exist_ok=True)
        caddy_path.write_text("\n".join(caddy_lines), encoding="utf-8")
        return caddy_path

    def write_html_redirect_pages(
        self, out_dir: Path, *, max_confidence_for_not_export: float | None = None
    ) -> dict[str, int]:
        """Write HTML redirect pages for selected redirects (only when source page is absent)."""
        if max_confidence_for_not_export is None:
            max_confidence_for_not_export = self._max_confidence_for_not_export

        selected = self._select_redirects_for_export(
            max_confidence_for_not_export=max_confidence_for_not_export
        )
        created = 0
        skipped_existing = 0
        skipped_unsafe_query = 0

        for candidate in selected:
            source = URL(candidate.source)
            target = URL(candidate.target)

            source_rel = safe_relative_path_for_page(source)
            source_q = source.raw_query_string
            if source_q:
                query_rel = safe_relative_path_for_query(
                    source_q, max_len=self._max_query_len_for_fs_mapping
                )
                if query_rel is None:
                    skipped_unsafe_query += 1
                    continue
                html_path = out_dir / "pages_q" / source_rel / query_rel / "index.html"
            else:
                html_path = out_dir / "pages" / source_rel / "index.html"

            if html_path.exists():
                skipped_existing += 1
                continue

            html_path.parent.mkdir(parents=True, exist_ok=True)
            html_path.write_text(
                _render_redirect_html(_relative_redirect_target(target)), encoding="utf-8"
            )
            created += 1

        return {
            "created": created,
            "skipped_existing": skipped_existing,
            "skipped_unsafe_query": skipped_unsafe_query,
        }
