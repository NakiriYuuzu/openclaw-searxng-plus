import asyncio

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from gateway.site_crawler import SiteCrawler


def _make_crawl_result(url: str, success: bool = True, content: str = "test content"):
    return {
        "url": url,
        "content": content if success else None,
        "markdown": content if success else None,
        "title": f"Title for {url}",
        "success": success,
        "partial": not success,
        "source": "crawl4ai",
    }


HTML_WITH_LINKS = """
<html><body>
<a href="/page2">Page 2</a>
<a href="/page3">Page 3</a>
<a href="/admin/secret">Admin</a>
</body></html>
"""


@pytest.fixture
def crawler():
    return SiteCrawler()


@pytest.mark.asyncio
class TestSiteCrawler:
    async def test_respects_max_pages(self, crawler):
        crawl_count = 0

        async def mock_crawl(url, options):
            nonlocal crawl_count
            crawl_count += 1
            return _make_crawl_result(url)

        with patch("gateway.site_crawler.crawl_url", new_callable=AsyncMock, side_effect=mock_crawl):
            with patch("gateway.site_crawler.discover_urls", new_callable=AsyncMock, return_value={
                "urls": [f"https://example.com/page{i}" for i in range(20)],
                "total": 20,
                "source": {"sitemap": 20, "links": 0},
            }):
                with patch("gateway.site_crawler.append_job_result", new_callable=AsyncMock):
                    with patch("gateway.site_crawler.set_job_state", new_callable=AsyncMock):
                        with patch("gateway.site_crawler.check_url_safety", new_callable=AsyncMock, return_value=True):
                            results = await crawler.crawl_site(
                                job_id="test_job",
                                url="https://example.com",
                                max_depth=1,
                                max_pages=5,
                            )
                            assert crawl_count <= 5

    async def test_exclude_patterns(self, crawler):
        crawled_urls = []

        async def mock_crawl(url, options):
            crawled_urls.append(url)
            return _make_crawl_result(url)

        with patch("gateway.site_crawler.crawl_url", new_callable=AsyncMock, side_effect=mock_crawl):
            with patch("gateway.site_crawler.discover_urls", new_callable=AsyncMock, return_value={
                "urls": [
                    "https://example.com/page1",
                    "https://example.com/admin/secret",
                    "https://example.com/page2",
                ],
                "total": 3,
                "source": {"sitemap": 3, "links": 0},
            }):
                with patch("gateway.site_crawler.append_job_result", new_callable=AsyncMock):
                    with patch("gateway.site_crawler.set_job_state", new_callable=AsyncMock):
                        with patch("gateway.site_crawler.check_url_safety", new_callable=AsyncMock, return_value=True):
                            await crawler.crawl_site(
                                job_id="test_job",
                                url="https://example.com",
                                max_pages=10,
                                exclude_patterns=["*/admin/*"],
                            )
                            assert not any("admin" in u for u in crawled_urls)

    async def test_include_patterns(self, crawler):
        crawled_urls = []

        async def mock_crawl(url, options):
            crawled_urls.append(url)
            return _make_crawl_result(url)

        with patch("gateway.site_crawler.crawl_url", new_callable=AsyncMock, side_effect=mock_crawl):
            with patch("gateway.site_crawler.discover_urls", new_callable=AsyncMock, return_value={
                "urls": [
                    "https://example.com/blog/post1",
                    "https://example.com/about",
                    "https://example.com/blog/post2",
                ],
                "total": 3,
                "source": {"sitemap": 3, "links": 0},
            }):
                with patch("gateway.site_crawler.append_job_result", new_callable=AsyncMock):
                    with patch("gateway.site_crawler.set_job_state", new_callable=AsyncMock):
                        with patch("gateway.site_crawler.check_url_safety", new_callable=AsyncMock, return_value=True):
                            await crawler.crawl_site(
                                job_id="test_job",
                                url="https://example.com",
                                max_pages=10,
                                include_patterns=["*/blog/*"],
                            )
                            assert all("blog" in u for u in crawled_urls)

    async def test_single_page_failure_continues(self, crawler):
        call_count = 0

        async def mock_crawl(url, options):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_crawl_result(url, success=False)
            return _make_crawl_result(url)

        with patch("gateway.site_crawler.crawl_url", new_callable=AsyncMock, side_effect=mock_crawl):
            with patch("gateway.site_crawler.discover_urls", new_callable=AsyncMock, return_value={
                "urls": ["https://example.com/fail", "https://example.com/ok"],
                "total": 2,
                "source": {"sitemap": 2, "links": 0},
            }):
                with patch("gateway.site_crawler.append_job_result", new_callable=AsyncMock):
                    with patch("gateway.site_crawler.set_job_state", new_callable=AsyncMock):
                        with patch("gateway.site_crawler.check_url_safety", new_callable=AsyncMock, return_value=True):
                            results = await crawler.crawl_site(
                                job_id="test_job",
                                url="https://example.com",
                                max_pages=10,
                            )
                            # 3 pages: seed url + 2 discovered urls
                            assert call_count == 3  # All pages attempted despite failure

    async def test_timeout_stops_crawl(self, crawler):
        call_count = 0

        async def mock_crawl(url, options):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(5)  # Slow crawl
            return _make_crawl_result(url)

        with patch("gateway.site_crawler.crawl_url", new_callable=AsyncMock, side_effect=mock_crawl):
            with patch("gateway.site_crawler.discover_urls", new_callable=AsyncMock, return_value={
                "urls": [f"https://example.com/page{i}" for i in range(10)],
                "total": 10,
                "source": {"sitemap": 10, "links": 0},
            }):
                with patch("gateway.site_crawler.append_job_result", new_callable=AsyncMock):
                    with patch("gateway.site_crawler.set_job_state", new_callable=AsyncMock):
                        with patch("gateway.site_crawler.check_url_safety", new_callable=AsyncMock, return_value=True):
                            results = await crawler.crawl_site(
                                job_id="test_job",
                                url="https://example.com",
                                max_pages=10,
                                timeout_s=1,  # 1 second timeout
                            )
                            assert call_count < 10  # Should not crawl all pages

    async def test_domain_consecutive_failure_cooldown(self, crawler):
        call_count = 0

        async def mock_crawl(url, options):
            nonlocal call_count
            call_count += 1
            return _make_crawl_result(url, success=False)

        with patch("gateway.site_crawler.crawl_url", new_callable=AsyncMock, side_effect=mock_crawl):
            with patch("gateway.site_crawler.discover_urls", new_callable=AsyncMock, return_value={
                "urls": [f"https://example.com/page{i}" for i in range(10)],
                "total": 10,
                "source": {"sitemap": 10, "links": 0},
            }):
                with patch("gateway.site_crawler.append_job_result", new_callable=AsyncMock):
                    with patch("gateway.site_crawler.set_job_state", new_callable=AsyncMock):
                        with patch("gateway.site_crawler.set_domain_cooldown", new_callable=AsyncMock) as mock_cooldown:
                            with patch("gateway.site_crawler.check_url_safety", new_callable=AsyncMock, return_value=True):
                                with patch("gateway.site_crawler.settings") as mock_settings:
                                    mock_settings.site_crawl_domain_fail_limit = 3
                                    await crawler.crawl_site(
                                        job_id="test_job",
                                        url="https://example.com",
                                        max_pages=10,
                                    )
                                    mock_cooldown.assert_called()

    async def test_robots_check_filters_urls(self, crawler):
        crawled_urls = []

        async def mock_crawl(url, options):
            crawled_urls.append(url)
            return _make_crawl_result(url)

        async def mock_is_allowed(url, **kwargs):
            return "/blocked" not in url

        mock_checker = MagicMock()
        mock_checker.is_allowed = AsyncMock(side_effect=mock_is_allowed)

        with patch("gateway.site_crawler.crawl_url", new_callable=AsyncMock, side_effect=mock_crawl):
            with patch("gateway.site_crawler.discover_urls", new_callable=AsyncMock, return_value={
                "urls": [
                    "https://example.com/allowed",
                    "https://example.com/blocked",
                ],
                "total": 2,
                "source": {"sitemap": 2, "links": 0},
            }):
                with patch("gateway.site_crawler.append_job_result", new_callable=AsyncMock):
                    with patch("gateway.site_crawler.set_job_state", new_callable=AsyncMock):
                        with patch("gateway.site_crawler.check_url_safety", new_callable=AsyncMock, return_value=True):
                            await crawler.crawl_site(
                                job_id="test_job",
                                url="https://example.com",
                                max_pages=10,
                                respect_robots=True,
                                robots_checker=mock_checker,
                            )
                            assert "https://example.com/allowed" in crawled_urls
                            assert "https://example.com/blocked" not in crawled_urls
