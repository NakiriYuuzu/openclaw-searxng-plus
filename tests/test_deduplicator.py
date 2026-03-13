from gateway.deduplicator import deduplicate


def _make_result(title: str, url: str, engines: list[str] | None = None, snippet: str = ""):
    return {
        "title": title,
        "url": url,
        "engines": engines or ["google"],
        "snippet": snippet,
        "score": 1.0,
    }


class TestDeduplicate:
    def test_no_duplicates(self):
        results = [
            _make_result("Alpha", "https://a.com"),
            _make_result("Beta", "https://b.com"),
        ]
        deduped = deduplicate(results)
        assert len(deduped) == 2

    def test_exact_url_dedup(self):
        results = [
            _make_result("Title A", "https://a.com", ["google"]),
            _make_result("Title A", "https://a.com", ["bing"]),
        ]
        deduped = deduplicate(results)
        assert len(deduped) == 1
        assert "google" in deduped[0]["engines"]
        assert "bing" in deduped[0]["engines"]
        assert deduped[0]["score"] == 2.0

    def test_fuzzy_title_dedup(self):
        results = [
            _make_result("How to learn Python programming", "https://a.com"),
            _make_result("How to learn Python programming!", "https://b.com"),
        ]
        deduped = deduplicate(results)
        assert len(deduped) == 1

    def test_different_titles_kept(self):
        results = [
            _make_result("Python tutorial", "https://a.com"),
            _make_result("Rust programming guide", "https://b.com"),
        ]
        deduped = deduplicate(results)
        assert len(deduped) == 2

    def test_longer_snippet_wins(self):
        results = [
            _make_result("Same Title", "https://a.com", snippet="short"),
            _make_result("Same Title", "https://a.com", snippet="a much longer and better snippet"),
        ]
        deduped = deduplicate(results)
        assert len(deduped) == 1
        assert "longer" in deduped[0]["snippet"]

    def test_empty_input(self):
        assert deduplicate([]) == []

    def test_single_input(self):
        results = [_make_result("Solo", "https://solo.com")]
        assert len(deduplicate(results)) == 1
