import asyncio
import logging
import re
from typing import Optional
from urllib.parse import urlparse

import httpx

from .cache import get_cached_content, is_domain_cooled_down, set_cached_content, set_domain_cooldown
from .config import settings
from .sanitizer import sanitize_content
from .security import check_url_safety

logger = logging.getLogger(__name__)

try:
    from readability import Document as ReadabilityDocument

    _HAS_READABILITY = True
except ImportError:
    _HAS_READABILITY = False

try:
    from bs4 import BeautifulSoup

    _HAS_BS4 = True
except ImportError:
    _HAS_BS4 = False

try:
    from playwright.async_api import async_playwright

    _HAS_PLAYWRIGHT = True
except ImportError:
    _HAS_PLAYWRIGHT = False

_HEADERS = {"User-Agent": "OpenClaw-SearchBot/1.0 (+https://openclaw.dev)"}


def _get_domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return ""
    return host.removeprefix("www.")


async def _fetch_readability(url: str, client: httpx.AsyncClient) -> tuple[Optional[str], bool]:
    """Stage 1: httpx + readability-lxml."""
    try:
        resp = await client.get(url, follow_redirects=True)
        resp.raise_for_status()
        html = resp.text

        if _HAS_READABILITY:
            doc = ReadabilityDocument(html)
            summary = doc.summary()
            if _HAS_BS4:
                text = BeautifulSoup(summary, "html.parser").get_text(separator=" ", strip=True)
            else:
                text = re.sub(r"<[^>]+>", " ", summary)
                text = re.sub(r"\s+", " ", text).strip()
            if len(text) > 100:
                return text, False

        if _HAS_BS4:
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            text = soup.get_text(separator=" ", strip=True)
            if len(text) > 100:
                return text, True

        return None, True
    except Exception:
        return None, True


async def _fetch_browser(url: str) -> tuple[Optional[str], bool]:
    """Stage 2: playwright browser rendering (optional)."""
    if not _HAS_PLAYWRIGHT or not settings.enable_browser_fallback:
        return None, True
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, timeout=int(settings.content_fetch_timeout * 1000))
            await page.wait_for_load_state("domcontentloaded")
            text = await page.inner_text("body")
            await browser.close()
            if text and len(text.strip()) > 100:
                return text.strip(), False
            return None, True
    except Exception:
        return None, True


async def fetch_content(url: str) -> tuple[Optional[str], bool]:
    """
    Content fetch fallback pipeline.
    Returns (content_text | None, is_partial).
    """
    # Domain cooldown check
    domain = _get_domain(url)
    if await is_domain_cooled_down(domain):
        return None, True

    # SSRF check
    if not await check_url_safety(url):
        return None, True

    # Content cache check
    cached = await get_cached_content(url)
    if cached is not None:
        return cached

    content: Optional[str] = None
    partial = True

    # Stage 1: readability
    async with httpx.AsyncClient(
        timeout=settings.content_fetch_timeout,
        headers=_HEADERS,
    ) as client:
        content, partial = await _fetch_readability(url, client)

    if content and len(content.strip()) > 100:
        sanitized = sanitize_content(content, settings.max_content_length)
        await set_cached_content(url, sanitized, partial)
        return sanitized, partial

    # Stage 2: browser fallback
    content, partial = await _fetch_browser(url)
    if content and len(content.strip()) > 100:
        sanitized = sanitize_content(content, settings.max_content_length)
        await set_cached_content(url, sanitized, partial)
        return sanitized, partial

    # Stage 3: all failed — cooldown + partial flag
    await set_domain_cooldown(domain)
    await set_cached_content(url, None, True)
    return None, True


async def fetch_contents_batch(
    results: list[dict],
    max_concurrent: int = 5,
) -> list[dict]:
    """Fetch content for a batch of results with bounded concurrency."""
    sem = asyncio.Semaphore(max_concurrent)

    async def _one(result: dict) -> dict:
        async with sem:
            content, partial = await fetch_content(result.get("original_url", result["url"]))
            result["content"] = content
            result["content_partial"] = partial
            return result

    await asyncio.gather(*[_one(r) for r in results])
    return results
