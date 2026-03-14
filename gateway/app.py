import logging
import time
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .cache import (
    close_redis,
    get_cached_results,
    get_job_result_count,
    get_job_results,
    set_cached_results,
)
from .config import settings
from .content_fetcher import fetch_contents_batch
from .crawl_client import crawl_results_batch, crawl_url
from .deduplicator import deduplicate
from .job_manager import JobManager
from .map_client import discover_urls
from .models import (
    CrawlProgress,
    CrawlRequest,
    CrawlResponse,
    CrawlResult,
    Freshness,
    JobCancelResponse,
    MapRequest,
    MapResponse,
    MapSourceStats,
    SearchRequest,
    SearchResponse,
    SearchResult,
    SiteCrawlJobResponse,
    SiteCrawlRequest,
    SiteCrawlResultItem,
    SiteCrawlStatusResponse,
)
from .normalizer import normalize_result
from .reranker import detect_language, rerank
from .robots import RobotsChecker
from .sanitizer import sanitize_content
from .searxng_client import query_searxng
from .security import check_rate_limit, verify_auth_token
from .site_crawler import SiteCrawler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_job_manager: JobManager | None = None
_robots_checker: RobotsChecker | None = None
_site_crawler: SiteCrawler | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _job_manager, _robots_checker, _site_crawler
    logger.info("OpenClaw Search Gateway starting")
    _job_manager = JobManager(max_concurrent=settings.job_max_concurrent)
    _robots_checker = RobotsChecker()
    _site_crawler = SiteCrawler()
    await _job_manager.recover_stale_jobs()
    yield
    await close_redis()
    logger.info("OpenClaw Search Gateway stopped")


app = FastAPI(
    title="OpenClaw Search Gateway",
    version="0.2.0",
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

    crawled = await crawl_url(req.url, req.crawl_options(), strip_links=req.stripLinks)
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


@app.post("/map", response_model=MapResponse)
async def map_urls(req: MapRequest, request: Request):
    start = time.time()
    _authorize_request(request)

    result = await discover_urls(
        req.url,
        include_patterns=req.includePatterns or None,
        use_sitemap=req.useSitemap,
        respect_robots=req.respectRobots,
        robots_checker=_robots_checker,
    )

    elapsed = (time.time() - start) * 1000
    return MapResponse(
        urls=result["urls"],
        total=result["total"],
        source=MapSourceStats(**result["source"]),
        timing_ms=round(elapsed, 1),
    )


@app.post("/crawl/site", response_model=SiteCrawlJobResponse)
async def crawl_site(req: SiteCrawlRequest, request: Request):
    _authorize_request(request)

    assert _job_manager is not None
    assert _site_crawler is not None

    async def run_crawl(job_id: str):
        timeout_s = min(req.timeoutMs // 1000, settings.site_crawl_timeout) if req.timeoutMs else settings.site_crawl_timeout
        await _site_crawler.crawl_site(
            job_id=job_id,
            url=req.url,
            max_depth=req.maxDepth,
            max_pages=req.maxPages,
            concurrency=req.concurrency,
            timeout_s=timeout_s,
            include_patterns=req.includePatterns or None,
            exclude_patterns=req.excludePatterns or None,
            respect_robots=req.respectRobots,
            format=req.format.value,
            robots_checker=_robots_checker,
        )

    try:
        job_id = await _job_manager.create_job(run_crawl)
    except RuntimeError as e:
        raise HTTPException(status_code=429, detail=str(e))

    state = _job_manager.get_local_state(job_id)
    return SiteCrawlJobResponse(
        jobId=job_id,
        status=state["status"] if state else "running",
        startedAt=state["startedAt"] if state else "",
    )


@app.get("/crawl/site/{job_id}", response_model=SiteCrawlStatusResponse)
async def get_crawl_site_status(job_id: str, request: Request, offset: int = 0, limit: int = 50):
    start = time.time()
    _authorize_request(request)

    limit = min(limit, 100)

    assert _job_manager is not None
    state = await _job_manager.get_job_status(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Job not found")

    results_raw = await get_job_results(job_id, offset, limit)
    result_total = await get_job_result_count(job_id)

    results = [SiteCrawlResultItem(**r) for r in results_raw]
    progress_data = state.get("progress", {})

    elapsed = (time.time() - start) * 1000
    return SiteCrawlStatusResponse(
        jobId=job_id,
        status=state.get("status", "unknown"),
        progress=CrawlProgress(**progress_data) if progress_data else CrawlProgress(),
        results=results,
        resultTotal=result_total,
        offset=offset,
        limit=limit,
        timing_ms=round(elapsed, 1),
    )


@app.delete("/crawl/site/{job_id}", response_model=JobCancelResponse)
async def cancel_crawl_site(job_id: str, request: Request):
    _authorize_request(request)

    assert _job_manager is not None

    state = await _job_manager.get_job_status(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Job not found")

    current_status = state.get("status", "")
    if current_status in ("completed", "failed", "cancelled"):
        return JSONResponse(
            status_code=409,
            content={"detail": f"Job already {current_status}", "status": current_status},
        )

    result = await _job_manager.cancel_job(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobCancelResponse(jobId=job_id, status="cancelled")


@app.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest, request: Request):
    start = time.time()
    _authorize_request(request)

    # --- Resolve language ---
    resolved_lang = req.lang if req.lang else detect_language(req.q)

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
        lang=resolved_lang,
        need_map=req.needMap,
        need_site_crawl=req.needSiteCrawl,
        format=req.format.value,
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
    raw_results = await query_searxng(
        req.q,
        time_range=time_range,
        language=resolved_lang,
    )

    # Fetch page 2 only when page 1 results are insufficient
    if len(raw_results) < req.topK:
        page2 = await query_searxng(
            req.q,
            time_range=time_range,
            pageno=2,
            language=resolved_lang,
        )
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

    # --- Rerank (language-aware) ---
    ranked = rerank(req.q, deduped, freshness=req.freshness.value, lang=resolved_lang)

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

    # --- Optional URL discovery (needMap) ---
    if req.needMap:
        seen_domains: set[str] = set()
        for r in top_results:
            domain = urlparse(r.get("url", "")).netloc
            if domain and domain not in seen_domains:
                seen_domains.add(domain)
                try:
                    map_result = await discover_urls(
                        r.get("url", ""),
                        use_sitemap=True,
                        respect_robots=req.crawlRespectRobots,
                        robots_checker=_robots_checker,
                    )
                    r["relatedUrls"] = map_result.get("urls", [])
                except Exception:
                    logger.debug("Map failed for %s", domain, exc_info=True)

    # --- Optional site crawl (needSiteCrawl) ---
    if req.needSiteCrawl and _job_manager is not None and _site_crawler is not None:
        seen_domains_crawl: set[str] = set()
        for r in top_results:
            domain = urlparse(r.get("url", "")).netloc
            if domain and domain not in seen_domains_crawl:
                seen_domains_crawl.add(domain)
                try:
                    target_url = r.get("original_url", r.get("url", ""))

                    async def _run_site_crawl(job_id: str, crawl_url_target=target_url):
                        await _site_crawler.crawl_site(
                            job_id=job_id,
                            url=crawl_url_target,
                            max_depth=req.siteCrawlMaxDepth,
                            max_pages=req.siteCrawlMaxPages,
                            concurrency=req.siteCrawlConcurrency,
                            include_patterns=req.siteCrawlIncludePatterns or None,
                            exclude_patterns=req.siteCrawlExcludePatterns or None,
                            respect_robots=req.crawlRespectRobots,
                            robots_checker=_robots_checker,
                        )

                    job_id = await _job_manager.create_job(_run_site_crawl)
                    r["siteCrawlJobId"] = job_id
                except RuntimeError:
                    logger.debug("Max concurrent jobs reached", exc_info=True)
                except Exception:
                    logger.debug("Site crawl job creation failed", exc_info=True)

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
                relatedUrls=r.get("relatedUrls"),
                siteCrawlJobId=r.get("siteCrawlJobId"),
            )
        )

    elapsed = (time.time() - start) * 1000

    # --- Cache store (exclude siteCrawlJobId) ---
    cache_results = []
    for r in results:
        d = r.model_dump()
        d.pop("siteCrawlJobId", None)
        cache_results.append(d)

    cache_payload = {
        "results": cache_results,
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
        lang=resolved_lang,
        need_map=req.needMap,
        need_site_crawl=req.needSiteCrawl,
        format=req.format.value,
    )

    return SearchResponse(
        results=results,
        timing_ms=round(elapsed, 1),
        query=req.q,
        total_found=total_found,
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(
        "Unhandled error on %s %s: %s",
        request.method,
        request.url.path,
        exc,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
