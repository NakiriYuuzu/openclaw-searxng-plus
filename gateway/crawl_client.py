import asyncio
import logging
import re
from typing import Any

import httpx

from .cache import get_cached_content, set_cached_content
from .config import settings
from .content_extractor import extract_main_content
from .models import CrawlOptions
from .sanitizer import (
    _BROKEN_DECIMAL_RE,
    _calc_link_density,
    clean_markdown,
    is_bot_detection_page,
    sanitize_content,
    should_skip_crawl,
)
from .security import check_url_safety

logger = logging.getLogger(__name__)


def _crawl_endpoint() -> str:
    base = settings.crawl_service_url.rstrip("/")
    path = settings.crawl_service_path
    if not path.startswith("/"):
        path = "/" + path
    return f"{base}{path}"


def _extract_result_payload(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        result = data.get("result")
        if isinstance(result, dict):
            return result

        results = data.get("results")
        if isinstance(results, dict):
            return results
        if isinstance(results, list):
            for item in results:
                if isinstance(item, dict):
                    return item

        nested_data = data.get("data")
        if isinstance(nested_data, dict):
            return _extract_result_payload(nested_data)

        return data

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                return item

    return {}


def _as_text(value: Any) -> str | None:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return None


def _extract_content(payload: dict[str, Any]) -> tuple[str | None, str | None, str | None, str | None, bool]:
    """Extract content fields from Crawl4AI response.

    Returns (content, markdown, title, raw_html, partial).
    """
    title = _as_text(payload.get("title"))

    markdown = None
    markdown_field = payload.get("markdown")
    if isinstance(markdown_field, dict):
        markdown = _as_text(markdown_field.get("fit_markdown")) or _as_text(markdown_field.get("raw_markdown"))
    else:
        markdown = _as_text(markdown_field)

    if markdown is None:
        markdown = _as_text(payload.get("fit_markdown")) or _as_text(payload.get("raw_markdown"))

    # Extract raw HTML for readability processing
    raw_html = _as_text(payload.get("cleaned_html")) or _as_text(payload.get("html"))

    content = None
    for candidate in (
        markdown,
        _as_text(payload.get("content")),
        _as_text(payload.get("text")),
        raw_html,
    ):
        if candidate:
            content = candidate
            break

    partial = bool(payload.get("partial") or payload.get("is_partial"))
    return content, markdown, title, raw_html, partial


def _build_payload_variants(url: str, options: CrawlOptions) -> list[dict[str, Any]]:
    # JS scroll script to trigger lazy loading and dynamic content
    js_scroll = (
        "await new Promise(r => setTimeout(r, 1000));"
        "window.scrollTo(0, document.body.scrollHeight / 2);"
        "await new Promise(r => setTimeout(r, 500));"
        "window.scrollTo(0, document.body.scrollHeight);"
        "await new Promise(r => setTimeout(r, 500));"
        "window.scrollTo(0, 0);"
    )

    crawler_config = {
        "stream": False,
        "page_timeout": max(options.timeoutMs, 30000),  # min 30s for JS
        "cache_mode": "bypass" if options.bypassCache else "enabled",
        "scan_full_page": options.maxDepth > 1,
        "max_depth": options.maxDepth,
        "max_pages": options.maxPages,
        "only_text": options.onlyMainContent,
        "delay_before_return_html": 2.0,  # Wait for JS rendering
        "js_code": js_scroll,
        "wait_for": "body",
    }

    return [
        {
            "urls": [url],
            "priority": 10,
            "crawler_config": crawler_config,
        },
        {
            "url": url,
            "maxDepth": options.maxDepth,
            "maxPages": options.maxPages,
            "timeoutMs": max(options.timeoutMs, 30000),
            "onlyMainContent": options.onlyMainContent,
            "bypassCache": options.bypassCache,
        },
        {
            "urls": [url],
        },
    ]


_STRIP_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
_STRIP_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]+\)")


def _strip_markdown_links(text: str) -> str:
    """Strip markdown links, keeping only the text: [text](url) → text."""
    text = _STRIP_IMAGE_RE.sub("", text)
    text = _STRIP_LINK_RE.sub(r"\1", text)
    return text


def _select_format(content: str | None, markdown: str | None, html: str | None, format: str) -> str | None:
    """Select content based on requested output format."""
    if format == "html":
        return html or content
    elif format == "text":
        return content
    else:  # "markdown" (default)
        return markdown or content


async def crawl_url(url: str, options: CrawlOptions, format: str = "markdown", strip_links: bool = False) -> dict[str, Any]:
    # Skip known anti-crawl domains
    from urllib.parse import urlparse as _urlparse
    _domain = _urlparse(url).netloc
    if should_skip_crawl(_domain):
        logger.debug("Skipping crawl for anti-crawl domain: %s", _domain)
        return {
            "url": url,
            "content": None,
            "markdown": None,
            "title": None,
            "success": False,
            "partial": True,
            "source": "crawl4ai",
        }

    if not await check_url_safety(url):
        return {
            "url": url,
            "content": None,
            "markdown": None,
            "title": None,
            "success": False,
            "partial": True,
            "source": "crawl4ai",
        }

    # Optional robots.txt check
    if options.respectRobots:
        from .robots import RobotsChecker
        checker = RobotsChecker()
        if not await checker.is_allowed(url):
            return {
                "url": url,
                "content": None,
                "markdown": None,
                "title": None,
                "success": False,
                "partial": True,
                "source": "crawl4ai",
            }

    if not options.bypassCache:
        cached = await get_cached_content(url)
        if cached is not None:
            cached_content, cached_partial = cached
            return {
                "url": url,
                "content": cached_content,
                "markdown": None,
                "title": None,
                "success": cached_content is not None,
                "partial": cached_partial,
                "source": "cache",
            }

    timeout_seconds = max(settings.crawl_service_timeout, options.timeoutMs / 1000.0)
    endpoint = _crawl_endpoint()

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        for payload in _build_payload_variants(url, options):
            try:
                resp = await client.post(endpoint, json=payload)
            except httpx.HTTPError:
                logger.debug("Crawl service HTTP error", exc_info=True)
                continue
            except Exception:
                logger.exception("Unexpected crawl service error")
                continue

            if resp.status_code >= 400:
                logger.debug("Crawl service returned status %d", resp.status_code)
                continue

            try:
                body = resp.json()
            except Exception:
                logger.debug("Crawl service returned non-JSON response")
                continue

            raw_result = _extract_result_payload(body)
            content, markdown, title, raw_html, partial = _extract_content(raw_result)

            # --- Dual-layer content cleaning ---
            # Layer 1: Try readability extraction from raw HTML
            readability_md = None
            if raw_html:
                readability_md, readability_title = extract_main_content(raw_html)
                if readability_md:
                    markdown = readability_md
                    content = readability_md
                    if readability_title and not title:
                        title = readability_title

            # Bot detection: discard bot verification pages
            if content and is_bot_detection_page(content):
                logger.debug("Bot detection page for %s, discarding", url)
                content = None
                markdown = None
            if markdown and is_bot_detection_page(markdown):
                markdown = None

            if content:
                # Layer 2: Clean markdown (link density, boilerplate, nav removal)
                cleaned_content = clean_markdown(content, strip_links=strip_links)
                cleaned_markdown = clean_markdown(markdown, strip_links=strip_links) if markdown else None

                # Fallback: if clean_markdown removed everything, try original
                # Crawl4AI content with cleaning (better than returning empty)
                if not cleaned_content and content != readability_md:
                    cleaned_content = clean_markdown(
                        content, strip_links=strip_links,
                        link_density_threshold=0.6,  # more permissive
                        min_block_length=50,
                    )
                if not cleaned_content and markdown and markdown != readability_md:
                    cleaned_content = clean_markdown(
                        markdown, strip_links=strip_links,
                        link_density_threshold=0.6,
                        min_block_length=50,
                    )

                # Auto-strip links if content is still link-heavy after cleaning
                if cleaned_content:
                    content_density = _calc_link_density(cleaned_content)
                    if content_density > 0.3:
                        logger.debug("Auto-stripping links (density=%.2f) for %s", content_density, url)
                        cleaned_content = _strip_markdown_links(cleaned_content)
                        if cleaned_markdown:
                            cleaned_markdown = _strip_markdown_links(cleaned_markdown)

                # Existing sanitization (injection, ads, whitespace)
                sanitized_content = sanitize_content(cleaned_content, settings.crawl_max_content_length)
                sanitized_markdown = (
                    sanitize_content(cleaned_markdown, settings.crawl_max_content_length)
                    if cleaned_markdown else None
                )

                # Fix broken decimals that sanitize_content may re-introduce
                sanitized_content = _BROKEN_DECIMAL_RE.sub(r"\1.\2", sanitized_content)
                if sanitized_markdown:
                    sanitized_markdown = _BROKEN_DECIMAL_RE.sub(r"\1.\2", sanitized_markdown)

                if not options.bypassCache:
                    await set_cached_content(url, sanitized_content, partial)

                selected_content = _select_format(
                    sanitized_content, sanitized_markdown, None, format
                )

                return {
                    "url": url,
                    "content": selected_content,
                    "markdown": sanitized_markdown,
                    "title": title,
                    "success": True,
                    "partial": partial,
                    "source": "crawl4ai",
                }

            # Request succeeded but no useful content was extracted.
            if not options.bypassCache:
                await set_cached_content(url, None, True)
            return {
                "url": url,
                "content": None,
                "markdown": None,
                "title": title,
                "success": False,
                "partial": True,
                "source": "crawl4ai",
            }

    if not options.bypassCache:
        await set_cached_content(url, None, True)

    return {
        "url": url,
        "content": None,
        "markdown": None,
        "title": None,
        "success": False,
        "partial": True,
        "source": "crawl4ai",
    }


async def crawl_results_batch(results: list[dict[str, Any]], options: CrawlOptions) -> list[dict[str, Any]]:
    if not results:
        return results

    concurrency = max(1, min(options.concurrency, settings.crawl_max_concurrent))
    sem = asyncio.Semaphore(concurrency)

    async def _crawl_one(result: dict[str, Any]) -> dict[str, Any]:
        async with sem:
            target_url = result.get("original_url", result.get("url", ""))
            if not target_url:
                result["content"] = None
                result["content_partial"] = True
                return result

            crawled = await crawl_url(target_url, options)
            result["content"] = crawled.get("content")
            result["content_partial"] = crawled.get("partial", True)
            return result

    await asyncio.gather(*[_crawl_one(r) for r in results])
    return results
