from datetime import datetime, timezone

from gateway.reranker import _get_domain, rerank, score_freshness, score_quality


class TestScoreQuality:
    def test_known_high_quality(self):
        assert score_quality("https://en.wikipedia.org/wiki/Test") > 0.9

    def test_known_medium_quality(self):
        assert score_quality("https://medium.com/article") > 0.6

    def test_unknown_domain(self):
        assert score_quality("https://random-site-xyz.com/page") == 0.50

    def test_subdomain_match(self):
        assert score_quality("https://docs.github.com/en") > 0.8


class TestScoreFreshness:
    def test_none_date(self):
        assert score_freshness(None, "any") == 0.5

    def test_very_recent(self):
        now = datetime.now(timezone.utc)
        score = score_freshness(now, "day")
        assert score > 0.9

    def test_old_content_day_filter(self):
        old = datetime(2020, 1, 1, tzinfo=timezone.utc)
        score = score_freshness(old, "day")
        assert score < 0.01

    def test_any_filter_lenient(self):
        old = datetime(2024, 1, 1, tzinfo=timezone.utc)
        score = score_freshness(old, "any")
        assert score > 0.01


class TestGetDomain:
    def test_strips_www(self):
        assert _get_domain("https://www.example.com/page") == "example.com"

    def test_no_www(self):
        assert _get_domain("https://example.com/page") == "example.com"


class TestRerank:
    def _make_results(self):
        return [
            {
                "title": "Python tutorial for beginners",
                "url": "https://docs.python.org/3/tutorial/",
                "snippet": "An informal introduction to Python",
                "engines": ["google", "bing"],
                "parsed_date": datetime(2025, 1, 1, tzinfo=timezone.utc),
                "score": 0.0,
            },
            {
                "title": "Random blog post about cooking",
                "url": "https://randomfood.blog/recipe",
                "snippet": "How to make pasta at home",
                "engines": ["duckduckgo"],
                "parsed_date": datetime(2024, 6, 1, tzinfo=timezone.utc),
                "score": 0.0,
            },
            {
                "title": "Learn Python programming language",
                "url": "https://stackoverflow.com/questions/python",
                "snippet": "Best resources for learning Python",
                "engines": ["google"],
                "parsed_date": None,
                "score": 0.0,
            },
        ]

    def test_rerank_returns_sorted(self):
        results = self._make_results()
        ranked = rerank("python tutorial", results)
        assert len(ranked) == 3
        scores = [r["score"] for r in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_relevant_result_ranked_higher(self):
        results = self._make_results()
        ranked = rerank("python tutorial", results)
        # Python-related results should rank above cooking blog
        urls = [r["url"] for r in ranked]
        cooking_idx = next(i for i, u in enumerate(urls) if "randomfood" in u)
        assert cooking_idx == len(ranked) - 1

    def test_empty_results(self):
        assert rerank("test", []) == []

    def test_single_result(self):
        result = [{
            "title": "Test",
            "url": "https://test.com",
            "snippet": "test",
            "engines": ["google"],
            "parsed_date": None,
            "score": 0.0,
        }]
        ranked = rerank("test", result)
        assert len(ranked) == 1
        assert ranked[0]["score"] > 0
