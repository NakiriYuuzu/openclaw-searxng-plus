import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from gateway.map_client import discover_urls


SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/page1</loc></url>
  <url><loc>https://example.com/page2</loc></url>
  <url><loc>https://example.com/blog/post1</loc></url>
</urlset>"""

SITEMAP_INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/sitemap-pages.xml</loc></sitemap>
</sitemapindex>"""

HTML_PAGE = """
<html><body>
<a href="/about">About</a>
<a href="https://example.com/contact">Contact</a>
<a href="https://other.com/external">External</a>
<a href="/blog/post2">Post 2</a>
</body></html>
"""


def _mock_response(text: str, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


@pytest.mark.asyncio
class TestDiscoverUrls:
    async def test_discovers_from_sitemap(self):
        async def mock_get(url, **kwargs):
            if "sitemap" in url:
                return _mock_response(SITEMAP_XML)
            return _mock_response(HTML_PAGE)

        with patch("gateway.map_client.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=mock_get)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with patch("gateway.map_client.check_url_safety", new_callable=AsyncMock, return_value=True):
                with patch("gateway.map_client.get_cached_map", new_callable=AsyncMock, return_value=None):
                    with patch("gateway.map_client.set_cached_map", new_callable=AsyncMock):
                        result = await discover_urls("https://example.com", use_sitemap=True)
                        assert result["total"] > 0
                        assert all(u.startswith("https://example.com") for u in result["urls"])
                        assert "source" in result

    async def test_excludes_external_links(self):
        async def mock_get(url, **kwargs):
            if "sitemap" in url:
                return _mock_response("", status_code=404)
            return _mock_response(HTML_PAGE)

        with patch("gateway.map_client.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=mock_get)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with patch("gateway.map_client.check_url_safety", new_callable=AsyncMock, return_value=True):
                with patch("gateway.map_client.get_cached_map", new_callable=AsyncMock, return_value=None):
                    with patch("gateway.map_client.set_cached_map", new_callable=AsyncMock):
                        result = await discover_urls("https://example.com", use_sitemap=True)
                        for url in result["urls"]:
                            assert "other.com" not in url

    async def test_include_patterns_filter(self):
        async def mock_get(url, **kwargs):
            if "sitemap" in url:
                return _mock_response(SITEMAP_XML)
            return _mock_response(HTML_PAGE)

        with patch("gateway.map_client.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=mock_get)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with patch("gateway.map_client.check_url_safety", new_callable=AsyncMock, return_value=True):
                with patch("gateway.map_client.get_cached_map", new_callable=AsyncMock, return_value=None):
                    with patch("gateway.map_client.set_cached_map", new_callable=AsyncMock):
                        result = await discover_urls(
                            "https://example.com",
                            include_patterns=["*/blog/*"],
                            use_sitemap=True,
                        )
                        assert all("blog" in u for u in result["urls"])

    async def test_sitemap_not_found_fallback(self):
        async def mock_get(url, **kwargs):
            if "sitemap" in url:
                return _mock_response("", status_code=404)
            return _mock_response(HTML_PAGE)

        with patch("gateway.map_client.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=mock_get)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with patch("gateway.map_client.check_url_safety", new_callable=AsyncMock, return_value=True):
                with patch("gateway.map_client.get_cached_map", new_callable=AsyncMock, return_value=None):
                    with patch("gateway.map_client.set_cached_map", new_callable=AsyncMock):
                        result = await discover_urls("https://example.com", use_sitemap=True)
                        assert result["source"]["sitemap"] == 0
                        assert result["source"]["links"] > 0

    async def test_sitemap_index_recursion(self):
        async def mock_get(url, **kwargs):
            if url.endswith("sitemap.xml"):
                return _mock_response(SITEMAP_INDEX_XML)
            elif url.endswith("sitemap-pages.xml"):
                return _mock_response(SITEMAP_XML)
            return _mock_response(HTML_PAGE)

        with patch("gateway.map_client.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=mock_get)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with patch("gateway.map_client.check_url_safety", new_callable=AsyncMock, return_value=True):
                with patch("gateway.map_client.get_cached_map", new_callable=AsyncMock, return_value=None):
                    with patch("gateway.map_client.set_cached_map", new_callable=AsyncMock):
                        result = await discover_urls("https://example.com", use_sitemap=True)
                        assert result["source"]["sitemap"] == 3

    async def test_returns_empty_on_total_failure(self):
        with patch("gateway.map_client.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("network error"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with patch("gateway.map_client.check_url_safety", new_callable=AsyncMock, return_value=True):
                with patch("gateway.map_client.get_cached_map", new_callable=AsyncMock, return_value=None):
                    result = await discover_urls("https://example.com", use_sitemap=True)
                    assert result["urls"] == []
                    assert result["total"] == 0
