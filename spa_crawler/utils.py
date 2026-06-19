from collections.abc import Callable, Iterable
from pathlib import Path
from urllib.parse import urlsplit

from yarl import URL

_ASCII_CONTROL_MAX = 31
_ASCII_DELETE = 127


def _relative_path_from_url(url: URL) -> str:
    """Return URL path without a leading slash."""
    return (url.path_safe or "/").lstrip("/")


def _normalize_posix_path_for_match(raw: str) -> str:
    """Normalize a path to canonical POSIX-prefix form for prefix matching."""
    parts = [part for part in raw.split("/") if part]
    if not parts:
        return "/"
    return "/" + "/".join(parts)


def _query_is_safe_for_caddy_mapping(raw_q: str, *, max_len: int) -> bool:
    """
    Return ``False`` for query strings that break ``{query}`` -> FS mapping.
    Reject values that allow directory traversal.
    """
    if not raw_q:
        return False
    if "\x00" in raw_q:
        return False
    if len(raw_q) > max_len:
        return False
    if "%" in raw_q:
        return False
    if raw_q.startswith("/"):
        return False
    if "\\" in raw_q:
        return False
    if any(ord(ch) <= _ASCII_CONTROL_MAX or ord(ch) == _ASCII_DELETE for ch in raw_q):
        return False

    parts = raw_q.split("/")
    return not any(part in ("", ".", "..") for part in parts)


def strip_or_none(v: str | None) -> str | None:
    """Trim a string and return ``None`` for empty values."""
    if v is None:
        return None
    return v.strip() or None


def map_nonblank[T](values: Iterable[str] | None, mapper: Callable[[str], T]) -> list[T]:
    """Apply ``mapper`` to non-blank values only."""
    out: list[T] = []
    for raw in values or []:
        s = strip_or_none(raw)
        if s:
            out.append(mapper(s))
    return out


def unique_preserve_order[T](values: Iterable[T]) -> list[T]:
    """Return unique values while preserving first-seen order."""
    seen: set[T] = set()
    out: list[T] = []
    for item in values:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def path_has_prefix(path: str, prefix: str) -> bool:
    """Match '/x' prefix as '/x' or '/x/...', but not '/x-other'."""
    prefix_norm = _normalize_posix_path_for_match(prefix)
    if prefix_norm == "/":
        return True
    path_norm = _normalize_posix_path_for_match(path)
    return path_norm == prefix_norm or path_norm.startswith(f"{prefix_norm}/")


def is_absolute_http_url(u: URL) -> bool:
    """Return ``True`` for absolute HTTP/HTTPS URLs with a host."""
    return u.scheme in {"http", "https"} and bool(u.host)


def clean_candidate_url_text(raw: str | None, candidate_url_trim_chars: str) -> str | None:
    """Trim candidate URL text and strip wrapper quote-like characters."""
    if raw is None:
        return None
    s = raw.strip().strip(candidate_url_trim_chars)
    return s or None


def clean_path_prefix(raw: str) -> str:
    """Validate and normalize a path-prefix value (``/x`` form)."""
    s = raw.strip()
    if not s:
        raise ValueError("non-blank value is required.")
    if "\\" in s:
        raise ValueError("backslash is not allowed in path prefix.")

    try:
        u = URL(s)
    except Exception as e:
        raise ValueError("valid path is required.") from e

    if u.scheme or u.host or u.user or u.password:
        raise ValueError("path-only value is required.")

    if u.query_string or u.fragment:
        raise ValueError("query and fragment are not allowed.")

    path = u.path or s
    parts = [part for part in path.split("/") if part]
    if any(part in (".", "..") for part in parts):
        raise ValueError("dot path segments are not allowed.")
    return _normalize_posix_path_for_match(path)


def clean_absolute_http_url(raw: str, *, drop_query: bool = True) -> URL:
    """Validate and normalize an absolute HTTP/HTTPS URL."""
    s = raw.strip()
    if not s:
        raise ValueError("non-blank value is required.")

    try:
        u = URL(s)
    except Exception as e:
        raise ValueError("valid absolute URL is required.") from e

    if not is_absolute_http_url(u):
        raise ValueError("http(s) absolute URL is required.")

    u = u.with_fragment(None).with_user(None).with_password(None)
    if drop_query:
        u = u.with_query(None)

    if u.path == "/" and str(u).endswith("/"):
        u = u.with_path("")
    return u


def raw_query_from_url(url_s: str) -> str:
    """Extract the raw query string from a URL text."""
    return urlsplit(url_s).query


def safe_relative_path_for_page(url: URL) -> Path:
    """Convert URL path to a safe relative directory path for page snapshots."""
    return Path(_relative_path_from_url(url))


def safe_relative_path_for_asset(url: URL) -> Path:
    """
    Convert URL path to a safe relative filesystem path.

    - Strip the leading slash.
    - Turn directory URLs into ``<dir>/index``.
    """
    path = _relative_path_from_url(url)
    if not path or path.endswith("/"):
        path = f"{path}index"
    return Path(path)


def canonicalize_page_url(u: URL) -> URL:
    """
    Canonicalize page URLs:
    - Drop the fragment.
    - Drop a trailing slash for non-root paths.
    """
    u = u.with_fragment(None)
    path = u.path or "/"
    if path != "/" and path.endswith("/"):
        u = u.with_path(path.rstrip("/"))
    return u


def safe_relative_path_for_query(raw_q: str, *, max_len: int) -> Path | None:
    """Return query as a relative path if it is safe for Caddy ``{query}`` mapping."""
    if not _query_is_safe_for_caddy_mapping(raw_q, max_len=max_len):
        return None
    return Path(*raw_q.split("/"))
