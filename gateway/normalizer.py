from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from dateutil import parser as dateparser

TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source", "si",
    "sxsrf", "ved", "ei", "gs_lcp", "sclient",
})


def normalize_url(url: str) -> str:
    """Canonicalize URL: lowercase host, strip tracking params & fragment."""
    try:
        parsed = urlparse(url)
    except Exception:
        return url

    qs = parse_qs(parsed.query, keep_blank_values=False)
    cleaned_qs = {k: v for k, v in qs.items() if k.lower() not in TRACKING_PARAMS}
    clean_query = urlencode(cleaned_qs, doseq=True)

    return urlunparse((
        parsed.scheme.lower(),
        parsed.netloc.lower().rstrip("."),
        parsed.path.rstrip("/") or "/",
        parsed.params,
        clean_query,
        "",
    ))


def parse_date(raw: Any) -> datetime | None:
    """Best-effort date parsing from SearXNG publishedDate field."""
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw
    try:
        return dateparser.parse(str(raw))
    except (ValueError, TypeError, OverflowError):
        return None


def normalize_result(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a single SearXNG result into a consistent internal dict."""
    return {
        "title": (raw.get("title") or "").strip(),
        "url": normalize_url(raw.get("url", "")),
        "original_url": raw.get("url", ""),
        "snippet": (raw.get("content") or raw.get("snippet") or "").strip(),
        "source": raw.get("engine", "unknown"),
        "engines": list(raw.get("engines", [])),
        "score": float(raw.get("score", 0.0)),
        "parsed_date": parse_date(raw.get("publishedDate")),
        "category": raw.get("category", "general"),
    }
