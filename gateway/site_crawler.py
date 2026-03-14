import asyncio
import logging
from collections import defaultdict
from fnmatch import fnmatch
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .cache import append_job_result, set_domain_cooldown, set_job_state
from .config import settings
from .crawl_client import crawl_url
from .map_client import discover_urls
from .models import CrawlOptions
from .robots import RobotsChecker
from .security import check_url_safety

logger = logging.getLogger(__name__)


def _extract_links_from_html(html: str, base_url: str) -> list[str]:
    """Extract same-domain links from HTML content."""
    try:
        soup = BeautifulSoup(html, "html.parser")
        domain = urlparse(base_url).netloc
        urls = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            absolute = urljoin(base_url, href)
            if urlparse(absolute).netloc == domain:
                urls.append(absolute)
        return urls
    except Exception:
        return []


class SiteCrawler:
    async def crawl_site(
        self,
        job_id: str,
        url: str,
        max_depth: int = 3,
        max_pages: int = 100,
        concurrency: int = 3,
        timeout_s: int = 300,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        respect_robots: bool = True,
        format: str = "markdown",
        robots_checker: RobotsChecker | None = None,
    ) -> list[dict[str, Any]]:
        sem = asyncio.Semaphore(concurrency)
        visited: set[str] = set()
        results: list[dict[str, Any]] = []
        progress = {"discovered": 0, "crawled": 0, "failed": 0}
        domain_failures: dict[str, int] = defaultdict(int)
        fail_limit = settings.site_crawl_domain_fail_limit

        if respect_robots and robots_checker is None:
            robots_checker = RobotsChecker()

        crawl_options = CrawlOptions(
            maxDepth=1,
            maxPages=1,
            timeoutMs=15000,
            concurrency=1,
            onlyMainContent=True,
            bypassCache=False,
            respectRobots=False,  # We handle robots at site_crawler level
        )

        # Discover initial URLs (depth 0)
        discovery = await discover_urls(url, include_patterns=include_patterns, use_sitemap=True)
        seed_urls = discovery.get("urls", [])
        if url not in seed_urls:
            seed_urls.insert(0, url)
        seed_urls = self._filter_urls(seed_urls, include_patterns, exclude_patterns)

        # SSRF check on seed URLs
        safe_seeds = []
        for u in seed_urls:
            if await check_url_safety(u):
                safe_seeds.append(u)
        seed_urls = safe_seeds

        progress["discovered"] = len(seed_urls)
        await self._update_progress(job_id, progress)

        # BFS queue: list of (url, depth) tuples
        queue: list[tuple[str, int]] = [(u, 0) for u in seed_urls]

        async def _crawl_one(target_url: str) -> dict[str, Any] | None:
            async with sem:
                if len(results) >= max_pages:
                    return None

                domain = urlparse(target_url).netloc

                # Domain cooldown check
                if domain_failures[domain] >= fail_limit:
                    return None

                # robots.txt check
                if respect_robots and robots_checker:
                    if not await robots_checker.is_allowed(target_url):
                        logger.debug("robots.txt blocks %s", target_url)
                        return None

                try:
                    result = await crawl_url(target_url, crawl_options)
                    item = {
                        "url": target_url,
                        "title": result.get("title"),
                        "content": result.get("content") or result.get("markdown"),
                        "html": result.get("html"),
                        "success": result.get("success", False),
                    }

                    if item["success"]:
                        progress["crawled"] += 1
                        domain_failures[domain] = 0  # Reset on success
                    else:
                        progress["failed"] += 1
                        domain_failures[domain] += 1
                        if domain_failures[domain] >= fail_limit:
                            await set_domain_cooldown(domain)
                            logger.warning("Domain %s cooled down after %d failures", domain, fail_limit)

                    results.append(item)
                    # Store without html in job results
                    store_item = {k: v for k, v in item.items() if k != "html"}
                    await append_job_result(job_id, store_item)
                    await self._update_progress(job_id, progress)
                    return item

                except Exception:
                    progress["failed"] += 1
                    domain_failures[domain] += 1
                    if domain_failures[domain] >= fail_limit:
                        await set_domain_cooldown(domain)
                    logger.debug("Failed to crawl %s", target_url, exc_info=True)
                    await self._update_progress(job_id, progress)
                    return None

        try:
            async with asyncio.timeout(timeout_s):
                while queue and len(results) < max_pages:
                    target_url, depth = queue.pop(0)

                    if target_url in visited:
                        continue
                    visited.add(target_url)

                    item = await _crawl_one(target_url)

                    # BFS: extract new URLs from crawled HTML if depth allows
                    if item and item.get("success") and depth < max_depth:
                        html = item.get("html") or item.get("content") or ""
                        if html:
                            new_urls = _extract_links_from_html(html, target_url)
                            new_urls = self._filter_urls(new_urls, include_patterns, exclude_patterns)
                            for new_url in new_urls:
                                if new_url not in visited and await check_url_safety(new_url):
                                    queue.append((new_url, depth + 1))
                                    progress["discovered"] += 1
                            await self._update_progress(job_id, progress)

        except asyncio.TimeoutError:
            logger.warning("Site crawl timed out for job %s after %ds", job_id, timeout_s)

        return results

    def _filter_urls(
        self,
        urls: list[str],
        include_patterns: list[str] | None,
        exclude_patterns: list[str] | None,
    ) -> list[str]:
        filtered = urls

        if include_patterns:
            filtered = [u for u in filtered if any(fnmatch(u, p) for p in include_patterns)]

        if exclude_patterns:
            filtered = [u for u in filtered if not any(fnmatch(u, p) for p in exclude_patterns)]

        return filtered

    async def _update_progress(self, job_id: str, progress: dict) -> None:
        state = {
            "jobId": job_id,
            "status": "running",
            "progress": progress.copy(),
        }
        await set_job_state(job_id, state)
