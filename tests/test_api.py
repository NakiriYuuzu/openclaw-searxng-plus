import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from gateway.app import app

HEADERS = {"Authorization": "Bearer test-token-12345"}


@pytest.fixture
def mock_searxng():
    """Mock SearXNG returning realistic results."""
    results = [
        {
            "title": "Python Tutorial",
            "url": "https://docs.python.org/3/tutorial/",
            "content": "An informal introduction to Python",
            "engine": "google",
            "engines": ["google", "bing"],
            "score": 2.0,
            "publishedDate": "2025-01-01",
            "category": "general",
        },
        {
            "title": "Learn Python - Full Course",
            "url": "https://www.youtube.com/watch?v=python123",
            "content": "A complete Python course for beginners",
            "engine": "duckduckgo",
            "engines": ["duckduckgo"],
            "score": 1.5,
            "publishedDate": "2025-02-15",
            "category": "general",
        },
        {
            "title": "Python (programming language) - Wikipedia",
            "url": "https://en.wikipedia.org/wiki/Python_(programming_language)",
            "content": "Python is a high-level programming language",
            "engine": "wikipedia",
            "engines": ["wikipedia", "google"],
            "score": 1.8,
            "publishedDate": "2025-03-01",
            "category": "general",
        },
    ]
    with patch("gateway.app.query_searxng", new_callable=AsyncMock, return_value=results):
        yield


@pytest.fixture
def mock_cache_miss():
    """Mock cache to always miss."""
    with (
        patch("gateway.app.get_cached_results", new_callable=AsyncMock, return_value=None),
        patch("gateway.app.set_cached_results", new_callable=AsyncMock),
    ):
        yield


@pytest.mark.asyncio
class TestHealthEndpoint:
    async def test_health(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
class TestSearchEndpoint:
    async def test_requires_auth(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/search", json={"q": "test"})
            assert resp.status_code == 401

    async def test_rejects_bad_token(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/search",
                json={"q": "test"},
                headers={"Authorization": "Bearer wrong-token"},
            )
            assert resp.status_code == 401

    async def test_successful_search(self, mock_searxng, mock_cache_miss):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/search",
                json={"q": "python tutorial", "topK": 3},
                headers=HEADERS,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "results" in data
            assert "timing_ms" in data
            assert "query" in data
            assert data["query"] == "python tutorial"
            assert len(data["results"]) <= 3

    async def test_result_structure(self, mock_searxng, mock_cache_miss):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/search",
                json={"q": "python", "topK": 5},
                headers=HEADERS,
            )
            data = resp.json()
            for result in data["results"]:
                assert "title" in result
                assert "url" in result
                assert "snippet" in result
                assert "score" in result
                assert "source" in result
                assert "content_partial" in result

    async def test_empty_query_rejected(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/search",
                json={"q": ""},
                headers=HEADERS,
            )
            assert resp.status_code == 422

    async def test_freshness_filter(self, mock_searxng, mock_cache_miss):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/search",
                json={"q": "news", "freshness": "day"},
                headers=HEADERS,
            )
            assert resp.status_code == 200

    async def test_no_results(self, mock_cache_miss):
        with patch("gateway.app.query_searxng", new_callable=AsyncMock, return_value=[]):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/search",
                    json={"q": "xyznonexistent"},
                    headers=HEADERS,
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["results"] == []
                assert data["total_found"] == 0


@pytest.mark.asyncio
class TestMapEndpoint:
    async def test_requires_auth(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/map", json={"url": "https://example.com"})
            assert resp.status_code == 401

    async def test_map_success(self):
        with patch("gateway.app.discover_urls", new_callable=AsyncMock, return_value={
            "urls": ["https://example.com/page1"],
            "total": 1,
            "source": {"sitemap": 1, "links": 0},
        }):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/map",
                    json={"url": "https://example.com"},
                    headers=HEADERS,
                )
                assert resp.status_code == 200
                data = resp.json()
                assert "urls" in data
                assert "total" in data
                assert "source" in data


@pytest.mark.asyncio
class TestCrawlSiteEndpoint:
    async def test_requires_auth(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/crawl/site", json={"url": "https://example.com"})
            assert resp.status_code == 401

    async def test_get_nonexistent_job(self):
        with patch("gateway.app._job_manager") as mock_jm:
            mock_jm.get_job_status = AsyncMock(return_value=None)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/crawl/site/job_nonexistent",
                    headers=HEADERS,
                )
                assert resp.status_code == 404

    async def test_delete_nonexistent_job(self):
        with patch("gateway.app._job_manager") as mock_jm:
            mock_jm.get_job_status = AsyncMock(return_value=None)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.delete(
                    "/crawl/site/job_nonexistent",
                    headers=HEADERS,
                )
                assert resp.status_code == 404

    async def test_delete_completed_job_returns_409(self):
        with patch("gateway.app._job_manager") as mock_jm:
            mock_jm.get_job_status = AsyncMock(return_value={"status": "completed", "jobId": "job_123"})
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.delete(
                    "/crawl/site/job_123",
                    headers=HEADERS,
                )
                assert resp.status_code == 409


@pytest.mark.asyncio
class TestCrawlSiteSuccess:
    async def test_create_site_crawl_job(self):
        with patch("gateway.app._job_manager") as mock_jm:
            mock_jm.create_job = AsyncMock(return_value="job_test123")
            mock_jm.get_local_state = MagicMock(return_value={
                "status": "running",
                "startedAt": "2026-03-14T00:00:00Z",
            })
            with patch("gateway.app._site_crawler", new=MagicMock()):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.post(
                        "/crawl/site",
                        json={"url": "https://example.com"},
                        headers=HEADERS,
                    )
                    assert resp.status_code == 200
                    data = resp.json()
                    assert data["jobId"] == "job_test123"
                    assert data["status"] == "running"


@pytest.mark.asyncio
class TestSearchIntegration:
    async def test_search_with_need_map(self, mock_searxng, mock_cache_miss):
        with patch("gateway.app.discover_urls", new_callable=AsyncMock, return_value={
            "urls": ["https://docs.python.org/3/library/"],
            "total": 1,
            "source": {"sitemap": 1, "links": 0},
        }):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/search",
                    json={"q": "python", "topK": 3, "needMap": True},
                    headers=HEADERS,
                )
                assert resp.status_code == 200
                data = resp.json()
                assert len(data["results"]) > 0
