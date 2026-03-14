import logging
import math
import threading
from datetime import datetime, timezone
from urllib.parse import urlparse

from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Jieba lazy loading (only loaded on first CJK query) — thread-safe
# ---------------------------------------------------------------------------
_jieba_initialized = False
_jieba_lock = threading.Lock()


def _ensure_jieba():
    global _jieba_initialized
    if _jieba_initialized:
        return
    with _jieba_lock:
        if not _jieba_initialized:
            import jieba
            jieba.setLogLevel(logging.WARNING)
            jieba.initialize()
            _jieba_initialized = True


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------
def detect_language(text: str) -> str:
    """Detect query language based on CJK character presence."""
    cjk_count = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    total_alpha = sum(1 for ch in text if ch.isalpha())
    cjk_ratio = cjk_count / max(total_alpha, 1)

    # Core insight: if query contains any CJK characters, the user likely
    # wants Chinese results (English users don't type Chinese characters).
    if cjk_count > 0:
        return "zh-TW"
    return "en"


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------
_ZH_STOP_WORDS = frozenset(
    "的 了 在 是 我 有 和 就 不 人 都 一 一個 上 也 很 到 說 要 去 你 會 著 沒有 看 好 自己 這"
    .split()
)


def tokenize(text: str, lang: str = "en") -> set[str]:
    """Tokenize text based on language. Returns a set of tokens."""
    text = text.lower()
    if lang.startswith("zh"):
        _ensure_jieba()
        import jieba
        tokens = set(jieba.lcut(text))
        tokens -= _ZH_STOP_WORDS
        tokens.discard("")
        tokens.discard(" ")
        return tokens
    return set(text.split())


# ---------------------------------------------------------------------------
# Domain quality — per-language tiers
# ---------------------------------------------------------------------------
DOMAIN_QUALITY: dict[str, dict[str, float]] = {
    "default": {
        # Tier 1 — authoritative reference
        "wikipedia.org": 0.95,
        "github.com": 0.90,
        "stackoverflow.com": 0.90,
        "docs.python.org": 0.95,
        "developer.mozilla.org": 0.95,
        "arxiv.org": 0.90,
        "nature.com": 0.90,
        "science.org": 0.88,
        # Tier 2 — reliable
        "medium.com": 0.70,
        "dev.to": 0.70,
        "hacker-news.firebaseio.com": 0.70,
    },
    "zh-TW": {
        # T1 — official / authoritative
        ".gov.tw": 0.95,
        ".edu.tw": 0.95,
        "cna.com.tw": 0.90,
        "udn.com": 0.88,
        "ltn.com.tw": 0.88,
        "ctee.com.tw": 0.88,
        "cnyes.com": 0.88,
        "twse.com.tw": 0.95,
        # T2 — professional
        "ithome.com.tw": 0.80,
        "techbang.com": 0.78,
        "moneydj.com": 0.80,
        "pansci.asia": 0.78,
        "ptt.cc": 0.65,
        "mobile01.com": 0.65,
        # T3 — tools
        "tw.stock.yahoo.com": 0.75,
        "goodinfo.tw": 0.75,
        "histock.tw": 0.72,
        "cmoney.tw": 0.72,
        "wantgoo.com": 0.72,
        "statementdog.com": 0.72,
        # Content platforms
        "vocus.cc": 0.60,
        "medium.com": 0.60,
        # Content farms — penalize
        "kknews.cc": 0.15,
        "twgreatdaily.com": 0.15,
        "read01.com": 0.15,
        "itw01.com": 0.15,
    },
    "en": {
        "reuters.com": 0.90,
        "apnews.com": 0.90,
        "bbc.com": 0.85,
        "nytimes.com": 0.85,
        "theguardian.com": 0.82,
        "washingtonpost.com": 0.82,
        "techcrunch.com": 0.75,
        "arstechnica.com": 0.78,
        "dev.to": 0.70,
        "medium.com": 0.68,
    },
}

DEFAULT_QUALITY = 0.50


def _get_domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _lookup_domain_quality(domain: str, quality_map: dict[str, float]) -> float | None:
    """Check domain against a quality map, supporting both exact and suffix matches."""
    for known, score in quality_map.items():
        if known.startswith("."):
            # TLD suffix match (e.g. ".gov.tw")
            if domain.endswith(known):
                return score
        else:
            if domain == known or domain.endswith("." + known):
                return score
    return None


def score_quality(url: str, lang: str = "en") -> float:
    """Score URL quality based on domain reputation, language-aware."""
    domain = _get_domain(url)

    # 1. Check language-specific map first
    lang_map = DOMAIN_QUALITY.get(lang, {})
    result = _lookup_domain_quality(domain, lang_map)
    if result is not None:
        return result

    # 2. Fallback to default map
    default_map = DOMAIN_QUALITY.get("default", {})
    result = _lookup_domain_quality(domain, default_map)
    if result is not None:
        return result

    return DEFAULT_QUALITY


# ---------------------------------------------------------------------------
# Language score
# ---------------------------------------------------------------------------
_TW_TLDS = frozenset({".tw", ".com.tw", ".org.tw", ".gov.tw", ".edu.tw"})


def score_language(url: str, snippet: str, preferred_lang: str) -> float:
    """Score how well a result matches the preferred language."""
    domain = _get_domain(url)

    # Domain TLD signal
    domain_score = 0.5
    if preferred_lang == "zh-TW":
        if any(domain.endswith(tld) for tld in _TW_TLDS):
            domain_score = 0.9
        elif domain.endswith(".cn") or domain.endswith(".hk"):
            domain_score = 0.7
    elif preferred_lang == "en":
        if any(domain.endswith(tld) for tld in (".com", ".org", ".io", ".dev", ".net")):
            domain_score = 0.7
        if any(domain.endswith(tld) for tld in _TW_TLDS):
            domain_score = 0.3

    # Snippet language signal
    snippet_cjk = sum(1 for ch in snippet if "\u4e00" <= ch <= "\u9fff")
    snippet_alpha = sum(1 for ch in snippet if ch.isalpha())
    snippet_cjk_ratio = snippet_cjk / max(snippet_alpha, 1)

    snippet_score = 0.5
    if preferred_lang.startswith("zh"):
        if snippet_cjk_ratio > 0.3:
            snippet_score = 0.9
        elif snippet_cjk_ratio > 0.1:
            snippet_score = 0.7
        elif snippet_cjk_ratio == 0 and snippet_alpha > 10:
            snippet_score = 0.2
    elif preferred_lang == "en":
        if snippet_cjk_ratio < 0.05:
            snippet_score = 0.8
        elif snippet_cjk_ratio > 0.3:
            snippet_score = 0.3

    # Weighted average: domain 0.4, snippet 0.6
    return domain_score * 0.4 + snippet_score * 0.6


# ---------------------------------------------------------------------------
# Snippet quality check
# ---------------------------------------------------------------------------
_NAV_PATTERNS = frozenset({"home", "首頁", "menu", "navigation", "skip to content", "跳至", "下載app", "訪客", "更多"})


def _snippet_quality_factor(snippet: str) -> float:
    """Return a multiplier (0.0-1.0) based on snippet quality."""
    if len(snippet) < 30:
        return 0.5

    # Check if snippet is mostly navigation text
    lower = snippet.lower()
    # Include · (middle dot) and · variants common in CJK nav bars
    nav_chars = sum(1 for ch in lower if ch in "|/>·\u00b7\u30fb")
    if nav_chars > len(lower) * 0.15:
        return 0.3

    # Count semicolons used as separators (e.g. "法人動向; 信用交易; 資金流向")
    semicolons = lower.count(";")
    if semicolons >= 4 and len(lower) < 200:
        return 0.4

    nav_words = sum(1 for w in _NAV_PATTERNS if w in lower)
    non_space = len(lower.replace(" ", ""))
    if non_space > 0 and nav_words >= 2 and len(lower) < 120:
        return 0.3

    return 1.0


# ---------------------------------------------------------------------------
# Relevance gate — pre-filter before scoring
# ---------------------------------------------------------------------------
def relevance_gate(query: str, results: list[dict], lang: str) -> list[dict]:
    """Filter out completely irrelevant results based on token overlap."""
    query_tokens = tokenize(query, lang)
    n_query = len(query_tokens)

    # Adaptive thresholds based on query length
    if n_query <= 2:
        penalty_threshold = 0.0
    elif n_query <= 5:
        penalty_threshold = 0.1
    else:
        penalty_threshold = 0.15

    filtered = []
    for r in results:
        doc_text = f"{r.get('title', '')} {r.get('snippet', '')}"
        doc_tokens = tokenize(doc_text, lang)
        overlap = len(query_tokens & doc_tokens)

        # Zero overlap → discard
        if overlap == 0:
            continue

        # Low overlap → mark for penalty
        if n_query > 2 and (overlap / n_query) < penalty_threshold:
            r["_relevance_penalty"] = 0.3

        filtered.append(r)
    return filtered


# ---------------------------------------------------------------------------
# Freshness scoring (unchanged)
# ---------------------------------------------------------------------------
def score_freshness(parsed_date: datetime | None, freshness: str) -> float:
    if parsed_date is None:
        return 0.5

    now = datetime.now(timezone.utc)
    dt = parsed_date.replace(tzinfo=timezone.utc) if parsed_date.tzinfo is None else parsed_date
    age_hours = max(0, (now - dt).total_seconds() / 3600)

    half_life_map = {"any": 8760, "day": 12, "week": 84, "month": 360}
    half_life = half_life_map.get(freshness, 720)

    return math.exp(-0.693 * age_hours / half_life)


# ---------------------------------------------------------------------------
# BM25 & TF-IDF — now language-aware
# ---------------------------------------------------------------------------
def _bm25_scores(query: str, documents: list[str], lang: str = "en") -> list[float]:
    if not documents:
        return []
    tokenized_docs = [list(tokenize(doc, lang)) for doc in documents]
    tokenized_query = list(tokenize(query, lang))
    bm25 = BM25Okapi(tokenized_docs)
    scores = bm25.get_scores(tokenized_query).tolist()
    mx = max(scores) if scores and max(scores) > 0 else 1.0
    return [s / mx for s in scores]


def _tfidf_scores(query: str, documents: list[str], lang: str = "en") -> list[float]:
    if not documents:
        return []
    try:
        if lang.startswith("zh"):
            # For Chinese, use custom tokenizer
            def zh_tokenizer(text):
                return list(tokenize(text, lang))

            vec = TfidfVectorizer(
                tokenizer=zh_tokenizer,
                token_pattern=None,
                max_features=5000,
            )
        else:
            vec = TfidfVectorizer(stop_words="english", max_features=5000)
        matrix = vec.fit_transform([query] + documents)
        sims = cosine_similarity(matrix[0:1], matrix[1:]).flatten()
        return sims.tolist()
    except Exception as exc:
        logger.warning("TF-IDF scoring failed: %s", exc)
        return [0.0] * len(documents)


# ---------------------------------------------------------------------------
# Main rerank function
# ---------------------------------------------------------------------------
def rerank(
    query: str,
    results: list[dict],
    freshness: str = "any",
    lang: str = "en",
) -> list[dict]:
    """Rerank results using hybrid lexical + semantic + quality + freshness + language scoring."""
    if not results:
        return []

    # --- Relevance gate: pre-filter irrelevant results ---
    results = relevance_gate(query, results, lang)
    if not results:
        return []

    documents = [
        f"{r.get('title', '')} {r.get('snippet', '')}" for r in results
    ]

    bm25 = _bm25_scores(query, documents, lang)
    tfidf = _tfidf_scores(query, documents, lang)

    # Validate score list lengths match results
    if len(bm25) != len(results) or len(tfidf) != len(results):
        logger.error(
            "Score length mismatch: bm25=%d, tfidf=%d, results=%d",
            len(bm25), len(tfidf), len(results),
        )
        return results

    for i, result in enumerate(results):
        lexical = bm25[i]
        semantic = tfidf[i]
        quality = score_quality(result.get("url", ""), lang)
        fresh = score_freshness(result.get("parsed_date"), freshness)
        lang_score = score_language(
            result.get("url", ""),
            result.get("snippet", ""),
            lang,
        )

        # Snippet quality multiplier
        snippet_factor = _snippet_quality_factor(result.get("snippet", ""))

        engine_count = len(result.get("engines", []))
        engine_bonus = min(0.1, (engine_count - 1) * 0.05)

        score = (
            settings.weight_lexical * lexical
            + settings.weight_semantic * semantic
            + settings.weight_quality * quality * snippet_factor
            + settings.weight_freshness * fresh
            + settings.weight_language * lang_score
            + engine_bonus
        )

        # Apply relevance penalty if marked by gate
        penalty = result.pop("_relevance_penalty", 1.0)
        if penalty < 1.0:
            score *= penalty

        result["score"] = round(score, 4)

    results.sort(key=lambda r: r["score"], reverse=True)
    return results
