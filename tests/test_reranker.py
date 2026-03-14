from datetime import datetime, timezone

from gateway.reranker import (
    _get_domain,
    _snippet_quality_factor,
    detect_language,
    relevance_gate,
    rerank,
    score_freshness,
    score_language,
    score_quality,
    tokenize,
)


class TestDetectLanguage:
    def test_pure_chinese(self):
        assert detect_language("台股走勢") == "zh-TW"

    def test_pure_english(self):
        assert detect_language("python tutorial") == "en"

    def test_mixed_mostly_chinese(self):
        assert detect_language("台積電 TSMC Q1") == "zh-TW"

    def test_mixed_few_chinese(self):
        assert detect_language("TSMC 台積電") == "zh-TW"

    def test_empty_string(self):
        assert detect_language("") == "en"

    def test_numbers_only(self):
        assert detect_language("12345") == "en"


class TestTokenize:
    def test_english_basic(self):
        tokens = tokenize("hello world", "en")
        assert "hello" in tokens
        assert "world" in tokens

    def test_chinese_basic(self):
        tokens = tokenize("台灣股票市場", "zh-TW")
        assert len(tokens) > 0
        # Should not contain stop words
        assert "的" not in tokens

    def test_empty_string(self):
        assert tokenize("", "en") == set()

    def test_english_with_punctuation(self):
        tokens = tokenize("hello, world! foo-bar", "en")
        assert len(tokens) > 0

    def test_numbers_in_text(self):
        tokens = tokenize("python 3.12 tutorial", "en")
        assert len(tokens) > 0

    def test_mixed_language(self):
        tokens = tokenize("Python 教學", "zh-TW")
        assert len(tokens) > 0


class TestScoreQuality:
    def test_known_high_quality_default(self):
        assert score_quality("https://en.wikipedia.org/wiki/Test") > 0.9

    def test_known_medium_quality_default(self):
        assert score_quality("https://medium.com/article") > 0.6

    def test_unknown_domain(self):
        assert score_quality("https://random-site-xyz.com/page") == 0.50

    def test_subdomain_match(self):
        assert score_quality("https://docs.github.com/en") > 0.8

    def test_zh_tw_gov_domain(self):
        assert score_quality("https://www.mof.gov.tw/", lang="zh-TW") > 0.9

    def test_zh_tw_edu_domain(self):
        assert score_quality("https://www.ntu.edu.tw/", lang="zh-TW") > 0.9

    def test_zh_tw_content_farm(self):
        assert score_quality("https://kknews.cc/article/123", lang="zh-TW") < 0.2

    def test_zh_tw_news(self):
        assert score_quality("https://www.cnyes.com/stock/123", lang="zh-TW") > 0.8

    def test_en_reuters(self):
        assert score_quality("https://reuters.com/article/123", lang="en") >= 0.90

    def test_fallback_to_default(self):
        # Wikipedia should be found in default map even when lang is zh-TW
        assert score_quality("https://en.wikipedia.org/wiki/Test", lang="zh-TW") > 0.9

    def test_high_quality_ranks_above_unknown(self):
        wiki_score = score_quality("https://en.wikipedia.org/wiki/Test")
        unknown_score = score_quality("https://random-site-xyz.com/page")
        assert wiki_score > unknown_score

    def test_content_farm_ranks_below_unknown(self):
        farm_score = score_quality("https://kknews.cc/article/123", lang="zh-TW")
        unknown_score = score_quality("https://random-site-xyz.com/page")
        assert farm_score < unknown_score


class TestScoreLanguage:
    def test_tw_domain_zh_query(self):
        score = score_language("https://cnyes.com/stock", "台積電今日股價上漲", "zh-TW")
        assert score > 0.7

    def test_en_domain_zh_query(self):
        score = score_language("https://example.com/page", "Some English content only", "zh-TW")
        assert score < 0.5

    def test_en_domain_en_query(self):
        score = score_language("https://example.com/page", "Python tutorial basics", "en")
        assert score > 0.6

    def test_tw_domain_en_query(self):
        score = score_language("https://example.com.tw/page", "Python tutorial", "en")
        en_score = score_language("https://example.com/page", "Python tutorial", "en")
        assert score < en_score


class TestSnippetQuality:
    def test_short_snippet(self):
        assert _snippet_quality_factor("short") == 0.5

    def test_nav_heavy_snippet(self):
        assert _snippet_quality_factor("Home | About | Contact | Menu | Help") < 0.5

    def test_normal_snippet(self):
        assert _snippet_quality_factor("This is a normal search result with useful information about Python programming.") == 1.0

    def test_semicolon_heavy_short_snippet(self):
        assert _snippet_quality_factor("法人動向; 信用交易; 資金流向; 技術分析; 基本面") < 1.0


class TestRelevanceGate:
    def test_removes_zero_overlap(self):
        results = [
            {"title": "Python tutorial", "snippet": "Learn Python programming"},
            {"title": "Cooking recipes", "snippet": "How to make pasta at home"},
        ]
        filtered = relevance_gate("python programming", results, "en")
        assert len(filtered) == 1
        assert "Python" in filtered[0]["title"]

    def test_keeps_relevant_results(self):
        results = [
            {"title": "Python tutorial", "snippet": "Learn Python basics"},
            {"title": "Python documentation", "snippet": "Official Python docs"},
        ]
        filtered = relevance_gate("python tutorial", results, "en")
        assert len(filtered) == 2

    def test_chinese_relevance(self):
        results = [
            {"title": "台股走勢分析", "snippet": "今日台股大盤走勢分析"},
            {"title": "WhatsApp group", "snippet": "Join our WhatsApp community"},
        ]
        filtered = relevance_gate("台股走勢", results, "zh-TW")
        assert len(filtered) == 1
        assert "台股" in filtered[0]["title"]

    def test_empty_results(self):
        assert relevance_gate("test", [], "en") == []


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

    def test_week_filter(self):
        old = datetime(2020, 1, 1, tzinfo=timezone.utc)
        score = score_freshness(old, "week")
        assert score < 0.01

    def test_month_filter(self):
        old = datetime(2020, 1, 1, tzinfo=timezone.utc)
        score = score_freshness(old, "month")
        assert score < 0.01

    def test_recent_content_week_filter(self):
        now = datetime.now(timezone.utc)
        score = score_freshness(now, "week")
        assert score > 0.9

    def test_recent_content_month_filter(self):
        now = datetime.now(timezone.utc)
        score = score_freshness(now, "month")
        assert score > 0.9


class TestGetDomain:
    def test_strips_www(self):
        assert _get_domain("https://www.example.com/page") == "example.com"

    def test_no_www(self):
        assert _get_domain("https://example.com/page") == "example.com"

    def test_malformed_url(self):
        assert _get_domain("not a url") == ""

    def test_empty_string(self):
        assert _get_domain("") == ""


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
        ranked = rerank("python tutorial", results, lang="en")
        assert len(ranked) >= 1
        scores = [r["score"] for r in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_relevant_result_ranked_higher(self):
        results = self._make_results()
        ranked = rerank("python tutorial", results, lang="en")
        # Cooking result should be filtered out or ranked last
        urls = [r["url"] for r in ranked]
        python_urls = [u for u in urls if "python" in u or "stackoverflow" in u]
        assert len(python_urls) >= 1

    def test_empty_results(self):
        assert rerank("test", []) == []

    def test_single_result(self):
        result = [{
            "title": "Test",
            "url": "https://test.com",
            "snippet": "test content here",
            "engines": ["google"],
            "parsed_date": None,
            "score": 0.0,
        }]
        ranked = rerank("test", result, lang="en")
        assert len(ranked) == 1
        assert ranked[0]["score"] > 0

    def test_chinese_query_rerank(self):
        results = [
            {
                "title": "台股走勢分析報告",
                "url": "https://cnyes.com/stock/analysis",
                "snippet": "今日台股大盤走勢分析，加權指數上漲",
                "engines": ["google"],
                "parsed_date": None,
                "score": 0.0,
            },
            {
                "title": "WhatsApp forum post",
                "url": "https://whatsapp-forum.example.com/post",
                "snippet": "Join our community group discussion",
                "engines": ["bing"],
                "parsed_date": None,
                "score": 0.0,
            },
        ]
        ranked = rerank("台股走勢", results, lang="zh-TW")
        assert len(ranked) > 0, "Expected at least one result after reranking"
        assert "cnyes" in ranked[0]["url"]

    def test_rerank_with_lang_parameter(self):
        results = self._make_results()
        ranked = rerank("python tutorial", results, freshness="any", lang="en")
        assert len(ranked) >= 1

    def test_multi_engine_bonus(self):
        results = [
            {
                "title": "Python docs",
                "url": "https://docs.python.org/3/",
                "snippet": "Python programming language docs",
                "engines": ["google", "bing", "duckduckgo"],
                "parsed_date": None,
                "score": 0.0,
            },
            {
                "title": "Python info",
                "url": "https://python.org/about/",
                "snippet": "Python programming language info",
                "engines": ["google"],
                "parsed_date": None,
                "score": 0.0,
            },
        ]
        ranked = rerank("python programming", results, lang="en")
        assert len(ranked) == 2
        # Multi-engine result should score higher (engine bonus)
        assert ranked[0]["url"] == "https://docs.python.org/3/"

    def test_stable_sort_identical_input(self):
        results = [
            {
                "title": "Test A",
                "url": "https://example.com/a",
                "snippet": "test content",
                "engines": ["google"],
                "parsed_date": None,
                "score": 0.0,
            },
            {
                "title": "Test B",
                "url": "https://example.com/b",
                "snippet": "test content",
                "engines": ["google"],
                "parsed_date": None,
                "score": 0.0,
            },
        ]
        ranked = rerank("test content", results, lang="en")
        assert len(ranked) == 2

    def test_malformed_url_does_not_crash(self):
        results = [
            {
                "title": "Test",
                "url": "",
                "snippet": "test content here",
                "engines": ["google"],
                "parsed_date": None,
                "score": 0.0,
            },
        ]
        ranked = rerank("test", results, lang="en")
        assert isinstance(ranked, list)
