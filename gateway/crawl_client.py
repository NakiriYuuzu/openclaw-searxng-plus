import asyncio
import logging
from typing import Any

import httpx

from .cache import get_cached_content, set_cached_content
from .config import settings
from .models import CrawlOptions
from .sanitizer import sanitize_content
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


def _extract_content(payload: dict[str, Any]) -> tuple[str | None, str | None, str | None, bool]:
    title = _as_text(payload.get("title"))

    markdown = None
    markdown_field = payload.get("markdown")
    if isinstance(markdown_field, dict):
        markdown = _as_text(markdown_field.get("fit_markdown")) or _as_text(markdown_field.get("raw_markdown"))
    else:
        markdown = _as_text(markdown_field)

    if markdown is None:
        markdown = _as_text(payload.get("fit_markdown")) or _as_text(payload.get("raw_markdown"))

    content = None
    for candidate in (
        markdown,
        _as_text(payload.get("content")),
        _as_text(payload.get("text")),
        _as_text(payload.get("cleaned_html")),
        _as_text(payload.get("html")),
    ):
        if candidate:
            content = candidate
            break

    partial = bool(payload.get("partial") or payload.get("is_partial"))
    return content, markdown, title, partial


def _build_payload_variants(url: str, options: CrawlOptions) -> list[dict[str, Any]]:
    crawler_config = {
        "stream": False,
        "page_timeout": options.timeoutMs,
        "cache_mode": "bypass" if options.bypassCache else "enabled",
        "scan_full_page": options.maxDepth > 1,
        "max_depth": options.maxDepth,
        "max_pages": options.maxPages,
        "only_text": options.onlyMainContent,
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
            "timeoutMs": options.timeoutMs,
            "onlyMainContent": options.onlyMainContent,
            "bypassCache": options.bypassCache,
        },
        {
            "urls": [url],
        },
    ]


async def crawl_url(url: str, options: CrawlOptions) -> dict[str, Any]:
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
            content, markdown, title, partial = _extract_content(raw_result)
            if content:
                sanitized_content = sanitize_content(content, settings.crawl_max_content_length)
                sanitized_markdown = (
                    sanitize_content(markdown, settings.crawl_max_content_length) if markdown else None
                )

                if not options.bypassCache:
                    await set_cached_content(url, sanitized_content, partial)

                return {
                    "url": url,
                    "content": sanitized_content,
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
