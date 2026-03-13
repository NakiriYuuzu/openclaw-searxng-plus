from datetime import datetime

from gateway.normalizer import normalize_result, normalize_url, parse_date


class TestNormalizeUrl:
    def test_strips_tracking_params(self):
        url = "https://example.com/page?utm_source=google&utm_medium=cpc&q=test"
        result = normalize_url(url)
        assert "utm_source" not in result
        assert "utm_medium" not in result
        assert "q=test" in result

    def test_lowercases_host(self):
        assert "example.com" in normalize_url("https://EXAMPLE.COM/path")

    def test_strips_fragment(self):
        result = normalize_url("https://example.com/page#section")
        assert "#" not in result

    def test_strips_trailing_slash(self):
        result = normalize_url("https://example.com/page/")
        assert result.endswith("/page")

    def test_root_path_preserved(self):
        result = normalize_url("https://example.com")
        assert result.endswith("/")

    def test_preserves_meaningful_params(self):
        url = "https://example.com/search?q=python&page=2"
        result = normalize_url(url)
        assert "q=python" in result
        assert "page=2" in result

    def test_handles_malformed_url(self):
        result = normalize_url("not-a-url")
        assert isinstance(result, str)


class TestParseDate:
    def test_iso_format(self):
        result = parse_date("2025-01-15T10:30:00Z")
        assert isinstance(result, datetime)
        assert result.year == 2025

    def test_datetime_passthrough(self):
        dt = datetime(2025, 6, 1)
        assert parse_date(dt) is dt

    def test_none_returns_none(self):
        assert parse_date(None) is None

    def test_empty_string_returns_none(self):
        assert parse_date("") is None

    def test_invalid_string_returns_none(self):
        assert parse_date("not-a-date-at-all-xyz") is None


class TestNormalizeResult:
    def test_basic_normalization(self):
        raw = {
            "title": "  Test Title  ",
            "url": "https://Example.COM/page?utm_source=x",
            "content": "Some snippet text",
            "engine": "google",
            "engines": ["google", "bing"],
            "score": 1.5,
            "publishedDate": "2025-03-01",
            "category": "general",
        }
        result = normalize_result(raw)
        assert result["title"] == "Test Title"
        assert "example.com" in result["url"]
        assert "utm_source" not in result["url"]
        assert result["snippet"] == "Some snippet text"
        assert result["source"] == "google"
        assert result["engines"] == ["google", "bing"]
        assert result["score"] == 1.5
        assert result["parsed_date"] is not None
        assert result["original_url"] == raw["url"]

    def test_missing_fields_default(self):
        result = normalize_result({})
        assert result["title"] == ""
        assert result["snippet"] == ""
        assert result["source"] == "unknown"
        assert result["parsed_date"] is None
