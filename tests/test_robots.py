import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from gateway.robots import RobotsChecker


@pytest.fixture
def checker():
    return RobotsChecker()


ROBOTS_ALLOW_ALL = """
User-agent: *
Allow: /
"""

ROBOTS_DISALLOW_ADMIN = """
User-agent: *
Disallow: /admin/
Disallow: /private/
Allow: /
"""

ROBOTS_DISALLOW_ALL = """
User-agent: *
Disallow: /
"""


@pytest.mark.asyncio
class TestRobotsChecker:
    async def test_allows_when_robots_permits(self, checker):
        with patch("gateway.robots.httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = ROBOTS_ALLOW_ALL
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with patch("gateway.robots.get_cached_robots", new_callable=AsyncMock, return_value=None):
                with patch("gateway.robots.set_cached_robots", new_callable=AsyncMock):
                    result = await checker.is_allowed("https://example.com/page")
                    assert result is True

    async def test_blocks_disallowed_path(self, checker):
        with patch("gateway.robots.httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = ROBOTS_DISALLOW_ADMIN
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with patch("gateway.robots.get_cached_robots", new_callable=AsyncMock, return_value=None):
                with patch("gateway.robots.set_cached_robots", new_callable=AsyncMock):
                    result = await checker.is_allowed("https://example.com/admin/settings")
                    assert result is False

    async def test_allows_when_robots_not_found(self, checker):
        with patch("gateway.robots.httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 404
            mock_resp.text = ""
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with patch("gateway.robots.get_cached_robots", new_callable=AsyncMock, return_value=None):
                with patch("gateway.robots.set_cached_robots", new_callable=AsyncMock):
                    result = await checker.is_allowed("https://example.com/anything")
                    assert result is True

    async def test_uses_cache_hit(self, checker):
        with patch("gateway.robots.get_cached_robots", new_callable=AsyncMock, return_value=ROBOTS_DISALLOW_ALL):
            result = await checker.is_allowed("https://example.com/page")
            assert result is False

    async def test_allows_on_fetch_error(self, checker):
        with patch("gateway.robots.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("connection failed"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with patch("gateway.robots.get_cached_robots", new_callable=AsyncMock, return_value=None):
                result = await checker.is_allowed("https://example.com/page")
                assert result is True
