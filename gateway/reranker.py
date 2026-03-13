import math
from datetime import datetime, timezone
from urllib.parse import urlparse

from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .config import settings

# Domain quality tiers
DOMAIN_QUALITY: dict[str, float] = {
    # Tier 1 — authoritative reference
    "wikipedia.org": 0.95,
    "github.com": 0.90,
    "stackoverflow.com": 0.90,
    "docs.python.org": 0.95,
    "developer.mozilla.org": 0.95,
    "arxiv.org": 0.90,
    "nature.com": 0.90,
    "science.org": 0.88,
    "reuters.com": 0.85,
    "apnews.com": 0.85,
    # Tier 2 — reliable
    "medium.com": 0.70,
    "dev.to": 0.70,
    "bbc.com": 0.80,
    "nytimes.com": 0.80,
    "theguardian.com": 0.78,
    "washingtonpost.com": 0.78,
    "techcrunch.com": 0.72,
    "arstechnica.com": 0.75,
    "hacker-news.firebaseio.com": 0.70,
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


def score_quality(url: str) -> float:
    domain = _get_domain(url)
    for known, score in DOMAIN_QUALITY.items():
        if domain == known or domain.endswith("." + known):
            return score
    return DEFAULT_QUALITY


def score_freshness(parsed_date: datetime | None, freshness: str) -> float:
    if parsed_date is None:
        return 0.5

    now = datetime.now(timezone.utc)
    dt = parsed_date.replace(tzinfo=timezone.utc) if parsed_date.tzinfo is None else parsed_date
    age_hours = max(0, (now - dt).total_seconds() / 3600)

    half_life_map = {"any": 8760, "day": 12, "week": 84, "month": 360}
    half_life = half_life_map.get(freshness, 720)

    return math.exp(-0.693 * age_hours / half_life)


def _bm25_scores(query: str, documents: list[str]) -> list[float]:
    if not documents:
        return []
    tokenized_docs = [doc.lower().split() for doc in documents]
    tokenized_query = query.lower().split()
    bm25 = BM25Okapi(tokenized_docs)
    scores = bm25.get_scores(tokenized_query).tolist()
    mx = max(scores) if scores and max(scores) > 0 else 1.0
    return [s / mx for s in scores]


def _tfidf_scores(query: str, documents: list[str]) -> list[float]:
    if not documents:
        return []
    try:
        vec = TfidfVectorizer(stop_words="english", max_features=5000)
        matrix = vec.fit_transform([query] + documents)
        sims = cosine_similarity(matrix[0:1], matrix[1:]).flatten()
        return sims.tolist()
    except ValueError:
        return [0.0] * len(documents)


def rerank(query: str, results: list[dict], freshness: str = "any") -> list[dict]:
    """Rerank results using hybrid lexical + semantic + quality + freshness scoring."""
    if not results:
        return []

    documents = [
        f"{r.get('title', '')} {r.get('snippet', '')}" for r in results
    ]

    bm25 = _bm25_scores(query, documents)
    tfidf = _tfidf_scores(query, documents)

    for i, result in enumerate(results):
        lexical = bm25[i] if i < len(bm25) else 0.0
        semantic = tfidf[i] if i < len(tfidf) else 0.0
        quality = score_quality(result.get("url", ""))
        fresh = score_freshness(result.get("parsed_date"), freshness)

        engine_count = len(result.get("engines", []))
        engine_bonus = min(0.1, (engine_count - 1) * 0.05)

        result["score"] = round(
            settings.weight_lexical * lexical
            + settings.weight_semantic * semantic
            + settings.weight_quality * quality
            + settings.weight_freshness * fresh
            + engine_bonus,
            4,
        )

    results.sort(key=lambda r: r["score"], reverse=True)
    return results
