import pytest

from gateway.security import check_rate_limit, check_url_safety, verify_auth_token


class TestCheckUrlSafety:
    @pytest.mark.asyncio
    async def test_blocks_localhost(self):
        assert await check_url_safety("http://localhost/admin") is False

    @pytest.mark.asyncio
    async def test_blocks_loopback(self):
        assert await check_url_safety("http://127.0.0.1/secret") is False

    @pytest.mark.asyncio
    async def test_blocks_private_10(self):
        assert await check_url_safety("http://10.0.0.1/internal") is False

    @pytest.mark.asyncio
    async def test_blocks_private_172(self):
        assert await check_url_safety("http://172.16.0.1/data") is False

    @pytest.mark.asyncio
    async def test_blocks_private_192(self):
        assert await check_url_safety("http://192.168.1.1/router") is False

    @pytest.mark.asyncio
    async def test_blocks_file_scheme(self):
        assert await check_url_safety("file:///etc/passwd") is False

    @pytest.mark.asyncio
    async def test_blocks_ftp_scheme(self):
        assert await check_url_safety("ftp://evil.com/file") is False

    @pytest.mark.asyncio
    async def test_blocks_no_hostname(self):
        assert await check_url_safety("http:///path") is False

    @pytest.mark.asyncio
    async def test_allows_public_https(self):
        result = await check_url_safety("https://www.google.com")
        assert result is True

    @pytest.mark.asyncio
    async def test_allows_public_http(self):
        result = await check_url_safety("http://example.com")
        assert result is True

    @pytest.mark.asyncio
    async def test_blocks_zero_ip(self):
        assert await check_url_safety("http://0.0.0.0/") is False


class TestRateLimit:
    def test_allows_within_limit(self):
        assert check_rate_limit("test-client-rl-1") is True

    def test_blocks_over_limit(self):
        client = "test-client-rl-overflow"
        # Fill up the bucket (using test env's high limit)
        from gateway.config import settings
        for _ in range(settings.rate_limit_rpm):
            check_rate_limit(client)
        assert check_rate_limit(client) is False


class TestVerifyAuthToken:
    def test_valid_token(self):
        assert verify_auth_token("test-token-12345") is True

    def test_invalid_token(self):
        assert verify_auth_token("wrong-token") is False

    def test_none_token(self):
        assert verify_auth_token(None) is False

    def test_empty_token(self):
        assert verify_auth_token("") is False
