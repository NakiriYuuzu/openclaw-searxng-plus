import asyncio
import logging
from fnmatch import fnmatch
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from .cache import get_cached_map, set_cached_map
from .config import settings
from .security import check_url_safety

logger = logging.getLogger(__name__)

_SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
_MAX_SITEMAP_DEPTH = 3


async def _fetch_sitemap(
    client: httpx.AsyncClient,
    url: str,
    depth: int = 0,
) -> list[str]:
    if depth > _MAX_SITEMAP_DEPTH:
        return []

    try:
        resp = await client.get(url, follow_redirects=True)
        if resp.status_code != 200:
            return []
    except Exception:
        logger.debug("Failed to fetch sitemap %s", url, exc_info=True)
        return []

    urls: list[str] = []
    try:
        root = ElementTree.fromstring(resp.text)

        # Check if this is a sitemap index
        sitemaps = root.findall(f"{{{_SITEMAP_NS}}}sitemap")
        if sitemaps:
            tasks = []
            for sm in sitemaps:
                loc = sm.find(f"{{{_SITEMAP_NS}}}loc")
                if loc is not None and loc.text:
                    tasks.append(_fetch_sitemap(client, loc.text.strip(), depth + 1))
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, list):
                    urls.extend(result)
            return urls

        # Regular sitemap
        for url_elem in root.findall(f"{{{_SITEMAP_NS}}}url"):
            loc = url_elem.find(f"{{{_SITEMAP_NS}}}loc")
            if loc is not None and loc.text:
                urls.append(loc.text.strip())
    except ElementTree.ParseError:
        logger.debug("Failed to parse sitemap XML from %s", url)

    return urls


def _extract_links(html: str, base_url: str) -> list[str]:
    try:
        soup = BeautifulSoup(html, "html.parser")
        urls = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            absolute = urljoin(base_url, href)
            urls.append(absolute)
        return urls
    except Exception:
        logger.debug("Failed to extract links from page", exc_info=True)
        return []


def _filter_same_domain(urls: list[str], domain: str) -> list[str]:
    return [u for u in urls if urlparse(u).netloc == domain]


async def _filter_ssrf_safe(urls: list[str]) -> list[str]:
    """Filter out URLs that fail SSRF safety checks."""
    safe = []
    for url in urls:
        if await check_url_safety(url):
            safe.append(url)
    return safe


def _apply_patterns(urls: list[str], include_patterns: list[str]) -> list[str]:
    if not include_patterns:
        return urls
    return [u for u in urls if any(fnmatch(u, p) for p in include_patterns)]


async def discover_urls(
    url: str,
    include_patterns: list[str] | None = None,
    use_sitemap: bool = True,
    respect_robots: bool = False,
    robots_checker: "RobotsChecker | None" = None,
    timeout: float | None = None,
) -> dict:
    parsed = urlparse(url)
    domain = parsed.netloc
    base_url = f"{parsed.scheme}://{domain}"
    effective_timeout = timeout or settings.map_timeout

    sitemap_urls: list[str] = []
    link_urls: list[str] = []

    try:
        async with asyncio.timeout(effective_timeout):
            async with httpx.AsyncClient(timeout=effective_timeout) as client:
                # Fetch sitemap
                if use_sitemap:
                    sitemap_url = f"{base_url}/sitemap.xml"
                    sitemap_urls = await _fetch_sitemap(client, sitemap_url)
                    sitemap_urls = _filter_same_domain(sitemap_urls, domain)

                # Fetch page links
                try:
                    resp = await client.get(url, follow_redirects=True)
                    if resp.status_code == 200:
                        link_urls = _extract_links(resp.text, base_url)
                        link_urls = _filter_same_domain(link_urls, domain)
                except Exception:
                    logger.debug("Failed to fetch page for link extraction", exc_info=True)

    except asyncio.TimeoutError:
        logger.debug("Map operation timed out for %s", url)
    except Exception:
        logger.debug("Map operation error for %s", url, exc_info=True)

    sitemap_count = len(sitemap_urls)
    link_only = [u for u in link_urls if u not in set(sitemap_urls)]
    link_count = len(link_only)

    all_urls = list(dict.fromkeys(sitemap_urls + link_urls))  # dedup preserving order

    # SSRF check on all discovered URLs
    all_urls = await _filter_ssrf_safe(all_urls)

    # robots.txt filtering
    if respect_robots and robots_checker:
        filtered = []
        for u in all_urls:
            if await robots_checker.is_allowed(u):
                filtered.append(u)
        all_urls = filtered

    if include_patterns:
        all_urls = _apply_patterns(all_urls, include_patterns)

    # Cache the full URL list
    if all_urls:
        await set_cached_map(domain, all_urls)

    return {
        "urls": all_urls,
        "total": len(all_urls),
        "source": {"sitemap": sitemap_count, "links": link_count},
    }
