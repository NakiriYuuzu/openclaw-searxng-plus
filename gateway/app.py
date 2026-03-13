import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .cache import close_redis, get_cached_results, set_cached_results
from .content_fetcher import fetch_contents_batch
from .crawl_client import crawl_results_batch, crawl_url
from .deduplicator import deduplicate
from .models import (
    CrawlRequest,
    CrawlResponse,
    CrawlResult,
    Freshness,
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from .normalizer import normalize_result
from .reranker import rerank
from .sanitizer import sanitize_content
from .searxng_client import query_searxng
from .security import check_rate_limit, verify_auth_token

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("OpenClaw Search Gateway starting")
    yield
    await close_redis()
    logger.info("OpenClaw Search Gateway stopped")


app = FastAPI(
    title="OpenClaw Search Gateway",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)


def _authorize_request(request: Request) -> None:
    raw_auth = request.headers.get("Authorization", "")
    token = raw_auth.removeprefix("Bearer ").strip()
    if not verify_auth_token(token):
        raise HTTPException(status_code=401, detail="Invalid or missing auth token")

    client_ip = request.client.host if request.client else "unknown"
    if not check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/crawl", response_model=CrawlResponse)
async def crawl(req: CrawlRequest, request: Request):
    start = time.time()
    _authorize_request(request)

    crawled = await crawl_url(req.url, req.crawl_options())
    elapsed = (time.time() - start) * 1000

    return CrawlResponse(
        result=CrawlResult(
            url=crawled.get("url", req.url),
            content=crawled.get("content"),
            title=crawled.get("title"),
            markdown=crawled.get("markdown"),
            success=bool(crawled.get("success", False)),
            partial=bool(crawled.get("partial", True)),
            source=crawled.get("source", "crawl4ai"),
        ),
        timing_ms=round(elapsed, 1),
    )


@app.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest, request: Request):
    start = time.time()
    _authorize_request(request)

    crawl_options = req.crawl_options() if req.needCrawl else None
    crawl_cache_key = crawl_options.cache_key() if crawl_options else ""

    # --- Cache hit? ---
    cached = await get_cached_results(
        req.q,
        req.freshness.value,
        req.topK,
        req.needContent,
        req.needCrawl,
        crawl_cache_key,
    )
    if cached is not None:
        elapsed = (time.time() - start) * 1000
        return SearchResponse(
            results=[SearchResult(**r) for r in cached["results"]],
            timing_ms=round(elapsed, 1),
            query=req.q,
            total_found=cached["total_found"],
        )

    # --- Query SearXNG ---
    time_range = None if req.freshness == Freshness.any else req.freshness.value
    raw_results = await query_searxng(req.q, time_range=time_range)

    # Fetch page 2 only when page 1 results are insufficient
    if len(raw_results) < req.topK:
        page2 = await query_searxng(req.q, time_range=time_range, pageno=2)
        raw_results.extend(page2)

    total_found = len(raw_results)

    if not raw_results:
        elapsed = (time.time() - start) * 1000
        return SearchResponse(
            results=[],
            timing_ms=round(elapsed, 1),
            query=req.q,
            total_found=0,
        )

    # --- Normalize ---
    normalized = [normalize_result(r) for r in raw_results]
    normalized = [r for r in normalized if r["url"] and r["title"]]

    # --- Deduplicate ---
    deduped = deduplicate(normalized)

    # --- Rerank ---
    ranked = rerank(req.q, deduped, freshness=req.freshness.value)

    # --- Trim to topK ---
    top_results = ranked[: req.topK]

    # --- Sanitize snippets ---
    for r in top_results:
        r["snippet"] = sanitize_content(r.get("snippet", ""), max_length=500)

    # --- Optional enrichment ---
    if req.needCrawl and crawl_options is not None:
        top_results = await crawl_results_batch(top_results, crawl_options)

        # Optional fallback to existing content fetcher when crawl misses.
        if req.needContent:
            missing_content = [r for r in top_results if not r.get("content")]
            if missing_content:
                await fetch_contents_batch(missing_content)
    elif req.needContent:
        top_results = await fetch_contents_batch(top_results)

    # --- Build response ---
    results = []
    for r in top_results:
        results.append(
            SearchResult(
                title=r.get("title", ""),
                url=r.get("original_url", r.get("url", "")),
                snippet=r.get("snippet", ""),
                content=r.get("content"),
                score=r.get("score", 0.0),
                source=r.get("source", "unknown"),
                content_partial=r.get("content_partial", False),
            )
        )

    elapsed = (time.time() - start) * 1000

    # --- Cache store ---
    cache_payload = {
        "results": [r.model_dump() for r in results],
        "total_found": total_found,
    }
    await set_cached_results(
        req.q,
        req.freshness.value,
        req.topK,
        cache_payload,
        req.needContent,
        req.needCrawl,
        crawl_cache_key,
    )

    return SearchResponse(
        results=results,
        timing_ms=round(elapsed, 1),
        query=req.q,
        total_found=total_found,
    )


@app.exception_handler(Exception)
async def global_exception_handler(_request: Request, exc: Exception):
    logger.exception("Unhandled error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
