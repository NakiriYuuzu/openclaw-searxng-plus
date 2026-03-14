# Search + Crawl Platform Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend openclaw-searxng-plus into a one-stop search + crawl + URL discovery platform comparable to Brave Search + Firecrawl + Cloudflare Crawl.

**Architecture:** Incremental extension of existing FastAPI gateway. New modules (`robots.py`, `map_client.py`, `job_manager.py`, `site_crawler.py`) added alongside existing code. Crawl4AI remains the rendering/extraction engine; gateway manages orchestration, task queues, and URL discovery. Redis stores async job state; asyncio handles execution.

**Tech Stack:** Python 3.12+, FastAPI, httpx, redis.asyncio, asyncio, urllib.robotparser, BeautifulSoup4, fnmatch

**Spec:** `docs/superpowers/specs/2026-03-14-search-crawl-platform-design.md`

---

## File Structure

### New files (to create)

| File | Responsibility |
|------|---------------|
| `gateway/robots.py` | robots.txt fetching, parsing, caching (Redis TTL 24h) |
| `gateway/map_client.py` | URL discovery via sitemap.xml + page link extraction |
| `gateway/job_manager.py` | Async job lifecycle (create/query/cancel), Redis state, asyncio.Task registry |
| `gateway/site_crawler.py` | BFS site crawler, depth/page limits, pattern filtering, progress tracking |
| `tests/test_robots.py` | Unit tests for robots.txt checker |
| `tests/test_map.py` | Unit tests for URL discovery |
| `tests/test_job_manager.py` | Unit tests for job lifecycle |
| `tests/test_site_crawler.py` | Unit tests for site crawler |

### Existing files (to modify)

| File | Changes |
|------|---------|
| `gateway/models.py` | Add `OutputFormat` enum, `SiteCrawlRequest`, `MapRequest`, `MapResponse`, etc. Extend `SearchRequest`, `SearchResult`, `CrawlRequest`, `CrawlOptions` |
| `gateway/config.py` | Add site crawl, map, robots, job settings |
| `gateway/cache.py` | Add robots cache, map cache, job state/results CRUD |
| `gateway/crawl_client.py` | Add `format` + `respectRobots` support |
| `gateway/app.py` | Add `/crawl/site`, `/map` routes; integrate `needMap`/`needSiteCrawl` into `/search`; init `JobManager` on startup |
| `tests/test_api.py` | Add tests for new endpoints and search integration |

---

## Chunk 1: Foundation — Models, Config, Cache

### Task 1: Extend Models

**Files:**
- Modify: `gateway/models.py`
- Test: `tests/test_api.py` (existing tests must still pass)

- [ ] **Step 1: Add `OutputFormat` enum and extend `CrawlOptions`**

Add to `gateway/models.py` after the `Freshness` enum:

```python
class OutputFormat(str, Enum):
    markdown = "markdown"
    text = "text"
    html = "html"
```

Add `respectRobots` to `CrawlOptions`:

```python
class CrawlOptions(BaseModel):
    maxDepth: int = Field(default=1, ge=1, le=5)
    maxPages: int = Field(default=1, ge=1, le=20)
    timeoutMs: int = Field(default=15000, ge=1000, le=120000)
    concurrency: int = Field(default=3, ge=1, le=10)
    onlyMainContent: bool = True
    bypassCache: bool = False
    respectRobots: bool = True

    def cache_key(self) -> str:
        return "|".join(
            [
                str(self.maxDepth),
                str(self.maxPages),
                str(self.timeoutMs),
                str(self.concurrency),
                str(self.onlyMainContent),
                str(self.bypassCache),
            ]
        )
```

- [ ] **Step 2: Extend `SearchRequest` with new fields**

Add after existing `crawlBypassCache` field:

```python
    crawlRespectRobots: bool = True

    # Output format (applies when needCrawl or needSiteCrawl is true)
    format: OutputFormat = OutputFormat.markdown

    # URL discovery
    needMap: bool = False

    # Site crawl (async)
    needSiteCrawl: bool = False
    siteCrawlMaxDepth: int = Field(default=1, ge=1, le=10)
    siteCrawlMaxPages: int = Field(default=5, ge=1, le=500)
    siteCrawlConcurrency: int = Field(default=3, ge=1, le=10)
    siteCrawlIncludePatterns: list[str] = Field(default_factory=list)
    siteCrawlExcludePatterns: list[str] = Field(default_factory=list)
```

Update `crawl_options()` to include `respectRobots`:

```python
    def crawl_options(self) -> CrawlOptions:
        return CrawlOptions(
            maxDepth=self.crawlMaxDepth,
            maxPages=self.crawlMaxPages,
            timeoutMs=self.crawlTimeoutMs,
            concurrency=self.crawlConcurrency,
            onlyMainContent=self.crawlOnlyMainContent,
            bypassCache=self.crawlBypassCache,
            respectRobots=self.crawlRespectRobots,
        )
```

- [ ] **Step 3: Extend `SearchResult` with optional fields**

```python
class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    content: str | None = None
    score: float
    source: str
    content_partial: bool = False
    relatedUrls: list[str] | None = None
    siteCrawlJobId: str | None = None
```

- [ ] **Step 4: Extend `CrawlRequest` with `format` and `respectRobots`**

```python
class CrawlRequest(BaseModel):
    url: str = Field(..., min_length=5, max_length=2048)
    maxDepth: int = Field(default=1, ge=1, le=5)
    maxPages: int = Field(default=1, ge=1, le=20)
    timeoutMs: int = Field(default=15000, ge=1000, le=120000)
    onlyMainContent: bool = True
    bypassCache: bool = False
    format: OutputFormat = OutputFormat.markdown
    respectRobots: bool = True

    # ... existing validate_http_url and crawl_options unchanged ...

    def crawl_options(self) -> CrawlOptions:
        return CrawlOptions(
            maxDepth=self.maxDepth,
            maxPages=self.maxPages,
            timeoutMs=self.timeoutMs,
            concurrency=1,
            onlyMainContent=self.onlyMainContent,
            bypassCache=self.bypassCache,
            respectRobots=self.respectRobots,
        )
```

- [ ] **Step 5: Add new request/response models**

Append to `gateway/models.py`:

```python
class SiteCrawlRequest(BaseModel):
    url: str = Field(..., min_length=5, max_length=2048)
    maxDepth: int = Field(default=3, ge=1, le=10)
    maxPages: int = Field(default=100, ge=1, le=500)
    format: OutputFormat = OutputFormat.markdown
    respectRobots: bool = True
    includePatterns: list[str] = Field(default_factory=list)
    excludePatterns: list[str] = Field(default_factory=list)
    concurrency: int = Field(default=3, ge=1, le=10)
    timeoutMs: int = Field(default=30000, ge=1000, le=600000)

    @field_validator("url")
    @classmethod
    def validate_http_url(cls, value: str) -> str:
        url = value.strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("url must be a valid http/https URL")
        return url


class SiteCrawlJobResponse(BaseModel):
    jobId: str
    status: str
    startedAt: str


class CrawlProgress(BaseModel):
    discovered: int = 0
    crawled: int = 0
    failed: int = 0


class SiteCrawlResultItem(BaseModel):
    url: str
    title: str | None = None
    content: str | None = None
    success: bool = True


class SiteCrawlStatusResponse(BaseModel):
    jobId: str
    status: str
    progress: CrawlProgress
    results: list[SiteCrawlResultItem] = Field(default_factory=list)
    resultTotal: int = 0
    offset: int = 0
    limit: int = 50
    timing_ms: float = 0.0


class JobCancelResponse(BaseModel):
    jobId: str
    status: str


class MapRequest(BaseModel):
    url: str = Field(..., min_length=5, max_length=2048)
    includePatterns: list[str] = Field(default_factory=list)
    respectRobots: bool = True
    useSitemap: bool = True

    @field_validator("url")
    @classmethod
    def validate_http_url(cls, value: str) -> str:
        url = value.strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("url must be a valid http/https URL")
        return url


class MapSourceStats(BaseModel):
    sitemap: int = 0
    links: int = 0


class MapResponse(BaseModel):
    urls: list[str]
    total: int
    source: MapSourceStats
    timing_ms: float
```

- [ ] **Step 6: Run existing tests to verify no regressions**

Run: `cd /Users/yuuzu/HanaokaYuuzu/Project/openclaw-searxng-plus && uv run pytest tests/ -v`
Expected: All existing tests PASS

- [ ] **Step 7: Commit**

```bash
git add gateway/models.py
git commit -m "feat(models): 🚀 add OutputFormat, SiteCrawl, Map models and extend SearchRequest

- Add OutputFormat enum (markdown/text/html)
- Add SiteCrawlRequest, SiteCrawlJobResponse, SiteCrawlStatusResponse
- Add MapRequest, MapResponse models
- Extend SearchRequest with needMap, needSiteCrawl, format, siteCrawl* fields
- Extend SearchResult with relatedUrls, siteCrawlJobId
- Extend CrawlRequest and CrawlOptions with format, respectRobots

Co-Authored-By: Yuuzu <yuuzu@yuuzu.net>"
```

### Task 2: Extend Config

**Files:**
- Modify: `gateway/config.py`

- [ ] **Step 1: Add new settings to `Settings` class**

Add before `model_config`:

```python
    # Site crawl
    site_crawl_max_depth: int = 3
    site_crawl_max_pages: int = 100
    site_crawl_timeout: int = 300
    site_crawl_concurrency: int = 3
    site_crawl_domain_fail_limit: int = 3

    # Map
    map_timeout: float = 10.0
    map_cache_ttl: int = 21600  # 6 hours

    # robots.txt
    robots_cache_ttl: int = 86400
    respect_robots_default: bool = True

    # Job management
    job_result_ttl: int = 86400
    job_max_concurrent: int = 10
```

- [ ] **Step 2: Run existing tests**

Run: `cd /Users/yuuzu/HanaokaYuuzu/Project/openclaw-searxng-plus && uv run pytest tests/ -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add gateway/config.py
git commit -m "feat(config): 🚀 add site crawl, map, robots, job settings

Co-Authored-By: Yuuzu <yuuzu@yuuzu.net>"
```

### Task 3: Extend Cache

**Files:**
- Modify: `gateway/cache.py`
- Test: verify via existing tests

- [ ] **Step 1: Add robots.txt cache methods**

Append to `gateway/cache.py`:

```python
# ---------------------------------------------------------------------------
# robots.txt cache
# ---------------------------------------------------------------------------
async def get_cached_robots(domain: str) -> str | None:
    try:
        r = await get_redis()
        return await r.get(f"oc:robots:{domain}")
    except Exception:
        return None


async def set_cached_robots(domain: str, robots_txt: str) -> None:
    try:
        r = await get_redis()
        await r.setex(f"oc:robots:{domain}", settings.robots_cache_ttl, robots_txt)
    except Exception:
        logger.debug("Robots cache write error", exc_info=True)
```

- [ ] **Step 2: Add map result cache methods**

```python
# ---------------------------------------------------------------------------
# Map result cache
# ---------------------------------------------------------------------------
async def get_cached_map(domain: str) -> list[str] | None:
    try:
        r = await get_redis()
        data = await r.get(_key("map", domain))
        return json.loads(data) if data else None
    except Exception:
        return None


async def set_cached_map(domain: str, urls: list[str]) -> None:
    try:
        r = await get_redis()
        await r.setex(_key("map", domain), settings.map_cache_ttl, json.dumps(urls))
    except Exception:
        logger.debug("Map cache write error", exc_info=True)
```

- [ ] **Step 3: Add job state/results cache methods**

```python
# ---------------------------------------------------------------------------
# Job state + results
# ---------------------------------------------------------------------------
async def get_job_state(job_id: str) -> dict | None:
    try:
        r = await get_redis()
        data = await r.get(f"oc:job:{job_id}")
        return json.loads(data) if data else None
    except Exception:
        return None


async def set_job_state(job_id: str, state: dict) -> None:
    try:
        r = await get_redis()
        await r.setex(
            f"oc:job:{job_id}",
            settings.job_result_ttl,
            json.dumps(state),
        )
    except Exception:
        logger.debug("Job state write error", exc_info=True)


async def append_job_result(job_id: str, result: dict) -> None:
    try:
        r = await get_redis()
        await r.rpush(f"oc:job:{job_id}:results", json.dumps(result))
        await r.expire(f"oc:job:{job_id}:results", settings.job_result_ttl)
    except Exception:
        logger.debug("Job result append error", exc_info=True)


async def get_job_results(job_id: str, offset: int = 0, limit: int = 50) -> list[dict]:
    try:
        r = await get_redis()
        raw = await r.lrange(f"oc:job:{job_id}:results", offset, offset + limit - 1)
        return [json.loads(item) for item in raw]
    except Exception:
        return []


async def get_job_result_count(job_id: str) -> int:
    try:
        r = await get_redis()
        return await r.llen(f"oc:job:{job_id}:results")
    except Exception:
        return 0


async def list_jobs_by_status(status: str) -> list[str]:
    """Scan for job keys and return IDs matching the given status."""
    result = []
    try:
        r = await get_redis()
        async for key in r.scan_iter(match="oc:job:*", count=100):
            if ":results" in key:
                continue
            data = await r.get(key)
            if data:
                state = json.loads(data)
                if state.get("status") == status:
                    result.append(state.get("jobId", key.split(":")[-1]))
    except Exception:
        logger.debug("Job scan error", exc_info=True)
    return result
```

- [ ] **Step 4: Update search cache key to include new flags**

Update `_search_cache_key` function:

```python
def _search_cache_key(
    query: str,
    freshness: str,
    top_k: int,
    need_content: bool,
    need_crawl: bool = False,
    crawl_options_key: str = "",
    lang: str = "",
    need_map: bool = False,
    need_site_crawl: bool = False,
    format: str = "markdown",
) -> str:
    parts = [
        query.strip(), freshness, str(top_k), str(need_content),
        str(need_crawl), str(need_map), str(need_site_crawl), format,
    ]
    if need_crawl:
        parts.append(crawl_options_key)
    if lang:
        parts.append(lang)
    return _key("search", *parts)
```

Update `get_cached_results` and `set_cached_results` signatures to accept the new params:

```python
async def get_cached_results(
    query: str,
    freshness: str,
    top_k: int,
    need_content: bool = False,
    need_crawl: bool = False,
    crawl_options_key: str = "",
    lang: str = "",
    need_map: bool = False,
    need_site_crawl: bool = False,
    format: str = "markdown",
) -> Optional[dict]:
    try:
        r = await get_redis()
        data = await r.get(
            _search_cache_key(
                query, freshness, top_k, need_content, need_crawl,
                crawl_options_key, lang, need_map, need_site_crawl, format,
            )
        )
        return json.loads(data) if data else None
    except json.JSONDecodeError:
        logger.debug("Cache contains invalid JSON")
        return None
    except aioredis.RedisError:
        logger.debug("Redis error reading cache", exc_info=True)
        return None
    except Exception:
        logger.debug("Cache read error", exc_info=True)
        return None


async def set_cached_results(
    query: str,
    freshness: str,
    top_k: int,
    payload: dict,
    need_content: bool = False,
    need_crawl: bool = False,
    crawl_options_key: str = "",
    lang: str = "",
    need_map: bool = False,
    need_site_crawl: bool = False,
    format: str = "markdown",
) -> None:
    try:
        r = await get_redis()
        await r.setex(
            _search_cache_key(
                query, freshness, top_k, need_content, need_crawl,
                crawl_options_key, lang, need_map, need_site_crawl, format,
            ),
            settings.cache_ttl,
            json.dumps(payload),
        )
    except aioredis.RedisError:
        logger.debug("Redis cache write error", exc_info=True)
    except Exception:
        logger.debug("Cache write error", exc_info=True)
```

- [ ] **Step 5: Update `app.py` cache calls to pass new params**

In `gateway/app.py`, update both `get_cached_results` and `set_cached_results` calls to pass the new keyword arguments with their defaults:

```python
    # In the search function, update get_cached_results call:
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

    # Update set_cached_results call similarly:
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
```

- [ ] **Step 6: Run existing tests**

Run: `cd /Users/yuuzu/HanaokaYuuzu/Project/openclaw-searxng-plus && uv run pytest tests/ -v`
Expected: All PASS (new cache params have defaults, backward compatible)

- [ ] **Step 7: Commit**

```bash
git add gateway/cache.py gateway/app.py
git commit -m "feat(cache): 🚀 add robots, map, job cache methods and extend search cache key

- Add robots.txt cache (TTL 24h)
- Add map result cache (TTL 6h)
- Add job state/results CRUD (Redis list + hash)
- Extend search cache key with needMap, needSiteCrawl, format

Co-Authored-By: Yuuzu <yuuzu@yuuzu.net>"
```

---

## Chunk 2: robots.txt Checker

### Task 4: Implement robots.py

**Files:**
- Create: `gateway/robots.py`
- Create: `tests/test_robots.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_robots.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/yuuzu/HanaokaYuuzu/Project/openclaw-searxng-plus && uv run pytest tests/test_robots.py -v`
Expected: FAIL (module does not exist)

- [ ] **Step 3: Implement `gateway/robots.py`**

```python
import logging
from io import StringIO
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from .cache import get_cached_robots, set_cached_robots

logger = logging.getLogger(__name__)

USER_AGENT = "OpenClawBot"
_FETCH_TIMEOUT = 5.0


class RobotsChecker:
    """Check URLs against robots.txt with Redis caching."""

    async def _fetch_robots_txt(self, domain: str, scheme: str) -> str | None:
        url = f"{scheme}://{domain}/robots.txt"
        try:
            async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT) as client:
                resp = await client.get(url, follow_redirects=True)
                if resp.status_code == 200:
                    return resp.text
                return None
        except Exception:
            logger.debug("Failed to fetch robots.txt for %s", domain, exc_info=True)
            return None

    async def _get_robots_txt(self, domain: str, scheme: str) -> str | None:
        cached = await get_cached_robots(domain)
        if cached is not None:
            return cached

        robots_txt = await self._fetch_robots_txt(domain, scheme)
        if robots_txt is not None:
            await set_cached_robots(domain, robots_txt)
        return robots_txt

    async def is_allowed(self, url: str, user_agent: str = USER_AGENT) -> bool:
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            scheme = parsed.scheme or "https"

            robots_txt = await self._get_robots_txt(domain, scheme)
            if robots_txt is None:
                return True  # Permissive: allow if not found or error

            parser = RobotFileParser()
            parser.parse(robots_txt.splitlines())
            return parser.can_fetch(user_agent, url)
        except Exception:
            logger.debug("robots.txt parse error for %s", url, exc_info=True)
            return True  # Permissive on error
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/yuuzu/HanaokaYuuzu/Project/openclaw-searxng-plus && uv run pytest tests/test_robots.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /Users/yuuzu/HanaokaYuuzu/Project/openclaw-searxng-plus && uv run pytest tests/ -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add gateway/robots.py tests/test_robots.py
git commit -m "feat(robots): 🚀 add robots.txt checker with Redis caching

- RobotsChecker class with is_allowed() method
- Fetches and parses robots.txt per domain
- Redis cache (TTL 24h) for parsed results
- Permissive fallback on fetch/parse errors
- Full test coverage

Co-Authored-By: Yuuzu <yuuzu@yuuzu.net>"
```

---

## Chunk 3: URL Discovery (Map)

### Task 5: Implement map_client.py

**Files:**
- Create: `gateway/map_client.py`
- Create: `tests/test_map.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_map.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from gateway.map_client import discover_urls


SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/page1</loc></url>
  <url><loc>https://example.com/page2</loc></url>
  <url><loc>https://example.com/blog/post1</loc></url>
</urlset>"""

SITEMAP_INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/sitemap-pages.xml</loc></sitemap>
</sitemapindex>"""

HTML_PAGE = """
<html><body>
<a href="/about">About</a>
<a href="https://example.com/contact">Contact</a>
<a href="https://other.com/external">External</a>
<a href="/blog/post2">Post 2</a>
</body></html>
"""


def _mock_response(text: str, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


@pytest.mark.asyncio
class TestDiscoverUrls:
    async def test_discovers_from_sitemap(self):
        async def mock_get(url, **kwargs):
            if "sitemap" in url:
                return _mock_response(SITEMAP_XML)
            return _mock_response(HTML_PAGE)

        with patch("gateway.map_client.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=mock_get)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with patch("gateway.map_client.get_cached_map", new_callable=AsyncMock, return_value=None):
                with patch("gateway.map_client.set_cached_map", new_callable=AsyncMock):
                    result = await discover_urls("https://example.com", use_sitemap=True)
                    assert result["total"] > 0
                    assert all(u.startswith("https://example.com") for u in result["urls"])
                    assert "source" in result

    async def test_excludes_external_links(self):
        async def mock_get(url, **kwargs):
            if "sitemap" in url:
                return _mock_response("", status_code=404)
            return _mock_response(HTML_PAGE)

        with patch("gateway.map_client.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=mock_get)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with patch("gateway.map_client.get_cached_map", new_callable=AsyncMock, return_value=None):
                with patch("gateway.map_client.set_cached_map", new_callable=AsyncMock):
                    result = await discover_urls("https://example.com", use_sitemap=True)
                    for url in result["urls"]:
                        assert "other.com" not in url

    async def test_include_patterns_filter(self):
        async def mock_get(url, **kwargs):
            if "sitemap" in url:
                return _mock_response(SITEMAP_XML)
            return _mock_response(HTML_PAGE)

        with patch("gateway.map_client.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=mock_get)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with patch("gateway.map_client.get_cached_map", new_callable=AsyncMock, return_value=None):
                with patch("gateway.map_client.set_cached_map", new_callable=AsyncMock):
                    result = await discover_urls(
                        "https://example.com",
                        include_patterns=["*/blog/*"],
                        use_sitemap=True,
                    )
                    assert all("blog" in u for u in result["urls"])

    async def test_sitemap_not_found_fallback(self):
        async def mock_get(url, **kwargs):
            if "sitemap" in url:
                return _mock_response("", status_code=404)
            return _mock_response(HTML_PAGE)

        with patch("gateway.map_client.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=mock_get)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with patch("gateway.map_client.get_cached_map", new_callable=AsyncMock, return_value=None):
                with patch("gateway.map_client.set_cached_map", new_callable=AsyncMock):
                    result = await discover_urls("https://example.com", use_sitemap=True)
                    assert result["source"]["sitemap"] == 0
                    assert result["source"]["links"] > 0

    async def test_sitemap_index_recursion(self):
        async def mock_get(url, **kwargs):
            if url.endswith("sitemap.xml"):
                return _mock_response(SITEMAP_INDEX_XML)
            elif url.endswith("sitemap-pages.xml"):
                return _mock_response(SITEMAP_XML)
            return _mock_response(HTML_PAGE)

        with patch("gateway.map_client.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=mock_get)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with patch("gateway.map_client.get_cached_map", new_callable=AsyncMock, return_value=None):
                with patch("gateway.map_client.set_cached_map", new_callable=AsyncMock):
                    result = await discover_urls("https://example.com", use_sitemap=True)
                    assert result["source"]["sitemap"] == 3

    async def test_returns_empty_on_total_failure(self):
        with patch("gateway.map_client.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("network error"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with patch("gateway.map_client.get_cached_map", new_callable=AsyncMock, return_value=None):
                result = await discover_urls("https://example.com", use_sitemap=True)
                assert result["urls"] == []
                assert result["total"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/yuuzu/HanaokaYuuzu/Project/openclaw-searxng-plus && uv run pytest tests/test_map.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `gateway/map_client.py`**

```python
import asyncio
import logging
from fnmatch import fnmatch
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from .cache import get_cached_map, set_cached_map
from .config import settings
from .security import check_url_safety

logger = logging.getLogger(__name__)

_SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
_MAX_SITEMAP_DEPTH = 3


async def _fetch_sitemap(
    client: httpx.AsyncClient,
    url: str,
    depth: int = 0,
) -> list[str]:
    if depth > _MAX_SITEMAP_DEPTH:
        return []

    try:
        resp = await client.get(url, follow_redirects=True)
        if resp.status_code != 200:
            return []
    except Exception:
        logger.debug("Failed to fetch sitemap %s", url, exc_info=True)
        return []

    urls: list[str] = []
    try:
        root = ElementTree.fromstring(resp.text)

        # Check if this is a sitemap index
        sitemaps = root.findall(f"{{{_SITEMAP_NS}}}sitemap")
        if sitemaps:
            tasks = []
            for sm in sitemaps:
                loc = sm.find(f"{{{_SITEMAP_NS}}}loc")
                if loc is not None and loc.text:
                    tasks.append(_fetch_sitemap(client, loc.text.strip(), depth + 1))
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, list):
                    urls.extend(result)
            return urls

        # Regular sitemap
        for url_elem in root.findall(f"{{{_SITEMAP_NS}}}url"):
            loc = url_elem.find(f"{{{_SITEMAP_NS}}}loc")
            if loc is not None and loc.text:
                urls.append(loc.text.strip())
    except ElementTree.ParseError:
        logger.debug("Failed to parse sitemap XML from %s", url)

    return urls


def _extract_links(html: str, base_url: str) -> list[str]:
    try:
        soup = BeautifulSoup(html, "html.parser")
        urls = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            absolute = urljoin(base_url, href)
            urls.append(absolute)
        return urls
    except Exception:
        logger.debug("Failed to extract links from page", exc_info=True)
        return []


def _filter_same_domain(urls: list[str], domain: str) -> list[str]:
    return [u for u in urls if urlparse(u).netloc == domain]


async def _filter_ssrf_safe(urls: list[str]) -> list[str]:
    """Filter out URLs that fail SSRF safety checks."""
    safe = []
    for url in urls:
        if await check_url_safety(url):
            safe.append(url)
    return safe


def _apply_patterns(urls: list[str], include_patterns: list[str]) -> list[str]:
    if not include_patterns:
        return urls
    return [u for u in urls if any(fnmatch(u, p) for p in include_patterns)]


async def discover_urls(
    url: str,
    include_patterns: list[str] | None = None,
    use_sitemap: bool = True,
    respect_robots: bool = False,
    robots_checker: "RobotsChecker | None" = None,
    timeout: float | None = None,
) -> dict:
    parsed = urlparse(url)
    domain = parsed.netloc
    base_url = f"{parsed.scheme}://{domain}"
    effective_timeout = timeout or settings.map_timeout

    sitemap_urls: list[str] = []
    link_urls: list[str] = []

    try:
        async with asyncio.timeout(effective_timeout):
            async with httpx.AsyncClient(timeout=effective_timeout) as client:
                # Fetch sitemap
                if use_sitemap:
                    sitemap_url = f"{base_url}/sitemap.xml"
                    sitemap_urls = await _fetch_sitemap(client, sitemap_url)
                    sitemap_urls = _filter_same_domain(sitemap_urls, domain)

                # Fetch page links
                try:
                    resp = await client.get(url, follow_redirects=True)
                    if resp.status_code == 200:
                        link_urls = _extract_links(resp.text, base_url)
                        link_urls = _filter_same_domain(link_urls, domain)
                except Exception:
                    logger.debug("Failed to fetch page for link extraction", exc_info=True)

    except asyncio.TimeoutError:
        logger.debug("Map operation timed out for %s", url)
    except Exception:
        logger.debug("Map operation error for %s", url, exc_info=True)

    sitemap_count = len(sitemap_urls)
    link_only = [u for u in link_urls if u not in set(sitemap_urls)]
    link_count = len(link_only)

    all_urls = list(dict.fromkeys(sitemap_urls + link_urls))  # dedup preserving order

    # SSRF check on all discovered URLs
    all_urls = await _filter_ssrf_safe(all_urls)

    # robots.txt filtering
    if respect_robots and robots_checker:
        filtered = []
        for u in all_urls:
            if await robots_checker.is_allowed(u):
                filtered.append(u)
        all_urls = filtered

    if include_patterns:
        all_urls = _apply_patterns(all_urls, include_patterns)

    # Cache the full URL list
    if all_urls:
        await set_cached_map(domain, all_urls)

    return {
        "urls": all_urls,
        "total": len(all_urls),
        "source": {"sitemap": sitemap_count, "links": link_count},
    }
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/yuuzu/HanaokaYuuzu/Project/openclaw-searxng-plus && uv run pytest tests/test_map.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /Users/yuuzu/HanaokaYuuzu/Project/openclaw-searxng-plus && uv run pytest tests/ -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add gateway/map_client.py tests/test_map.py
git commit -m "feat(map): 🚀 add URL discovery via sitemap + page link extraction

- discover_urls() with sitemap.xml parsing (recursive index support)
- Page link extraction via BeautifulSoup
- Same-domain filtering, include pattern support
- Wall-clock timeout, Redis caching
- Full test coverage

Co-Authored-By: Yuuzu <yuuzu@yuuzu.net>"
```

---

## Chunk 4: Job Manager

### Task 6: Implement job_manager.py

**Files:**
- Create: `gateway/job_manager.py`
- Create: `tests/test_job_manager.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_job_manager.py`:

```python
import asyncio

import pytest
from unittest.mock import AsyncMock, patch

from gateway.job_manager import JobManager


@pytest.fixture
def manager():
    return JobManager(max_concurrent=3)


@pytest.mark.asyncio
class TestJobManager:
    async def test_create_job(self, manager):
        async def dummy_task(job_id: str):
            await asyncio.sleep(10)

        with patch("gateway.job_manager.set_job_state", new_callable=AsyncMock):
            job_id = await manager.create_job(dummy_task)
            assert job_id.startswith("job_")

            state = manager.get_local_state(job_id)
            assert state is not None
            assert state["status"] == "running"

            # Cleanup
            await manager.cancel_job(job_id)

    async def test_cancel_job(self, manager):
        event = asyncio.Event()

        async def blocking_task(job_id: str):
            await event.wait()

        with patch("gateway.job_manager.set_job_state", new_callable=AsyncMock):
            job_id = await manager.create_job(blocking_task)
            result = await manager.cancel_job(job_id)
            assert result["status"] == "cancelled"

    async def test_cancel_nonexistent_job(self, manager):
        result = await manager.cancel_job("job_nonexistent")
        assert result is None

    async def test_max_concurrent_limit(self, manager):
        events = []

        async def blocking_task(job_id: str):
            e = asyncio.Event()
            events.append(e)
            await e.wait()

        with patch("gateway.job_manager.set_job_state", new_callable=AsyncMock):
            for _ in range(3):
                await manager.create_job(blocking_task)

            with pytest.raises(RuntimeError, match="concurrent"):
                await manager.create_job(blocking_task)

            # Cleanup
            for e in events:
                e.set()
            await asyncio.sleep(0.1)

    async def test_job_completes_successfully(self, manager):
        async def quick_task(job_id: str):
            pass  # completes immediately

        with patch("gateway.job_manager.set_job_state", new_callable=AsyncMock) as mock_set:
            job_id = await manager.create_job(quick_task)
            await asyncio.sleep(0.1)  # let task complete

            # Should have been called with "completed" status
            calls = [c for c in mock_set.call_args_list if c[0][1].get("status") == "completed"]
            assert len(calls) > 0

    async def test_job_failure_recorded(self, manager):
        async def failing_task(job_id: str):
            raise ValueError("something broke")

        with patch("gateway.job_manager.set_job_state", new_callable=AsyncMock) as mock_set:
            job_id = await manager.create_job(failing_task)
            await asyncio.sleep(0.1)

            calls = [c for c in mock_set.call_args_list if c[0][1].get("status") == "failed"]
            assert len(calls) > 0

    async def test_recover_marks_running_as_failed(self, manager):
        with patch("gateway.job_manager.list_jobs_by_status", new_callable=AsyncMock, return_value=["job_old1", "job_old2"]):
            with patch("gateway.job_manager.get_job_state", new_callable=AsyncMock, return_value={"jobId": "job_old1", "status": "running"}):
                with patch("gateway.job_manager.set_job_state", new_callable=AsyncMock) as mock_set:
                    await manager.recover_stale_jobs()
                    failed_calls = [
                        c for c in mock_set.call_args_list
                        if c[0][1].get("status") == "failed"
                        and c[0][1].get("reason") == "server restarted"
                    ]
                    assert len(failed_calls) >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/yuuzu/HanaokaYuuzu/Project/openclaw-searxng-plus && uv run pytest tests/test_job_manager.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `gateway/job_manager.py`**

```python
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

from .cache import get_job_state, list_jobs_by_status, set_job_state

logger = logging.getLogger(__name__)


class JobManager:
    def __init__(self, max_concurrent: int = 10):
        self._max_concurrent = max_concurrent
        self._tasks: dict[str, asyncio.Task] = {}
        self._local_state: dict[str, dict[str, Any]] = {}

    def _generate_id(self) -> str:
        return f"job_{uuid.uuid4().hex[:12]}"

    @property
    def active_count(self) -> int:
        return sum(1 for t in self._tasks.values() if not t.done())

    def get_local_state(self, job_id: str) -> dict[str, Any] | None:
        return self._local_state.get(job_id)

    async def create_job(
        self,
        coro_fn: Callable[[str], Coroutine[Any, Any, None]],
    ) -> str:
        if self.active_count >= self._max_concurrent:
            raise RuntimeError(
                f"Max concurrent site crawl jobs ({self._max_concurrent}) reached"
            )

        job_id = self._generate_id()
        now = datetime.now(timezone.utc).isoformat()

        state = {
            "jobId": job_id,
            "status": "running",
            "startedAt": now,
        }
        self._local_state[job_id] = state
        await set_job_state(job_id, state)

        task = asyncio.create_task(self._run_job(job_id, coro_fn))
        self._tasks[job_id] = task

        return job_id

    async def _run_job(
        self,
        job_id: str,
        coro_fn: Callable[[str], Coroutine[Any, Any, None]],
    ) -> None:
        try:
            await coro_fn(job_id)
            state = {
                "jobId": job_id,
                "status": "completed",
                "completedAt": datetime.now(timezone.utc).isoformat(),
            }
        except asyncio.CancelledError:
            state = {
                "jobId": job_id,
                "status": "cancelled",
            }
        except Exception as exc:
            logger.exception("Job %s failed", job_id)
            state = {
                "jobId": job_id,
                "status": "failed",
                "error": str(exc),
            }

        self._local_state[job_id] = state
        await set_job_state(job_id, state)

    async def cancel_job(self, job_id: str) -> dict[str, Any] | None:
        task = self._tasks.get(job_id)
        if task is None:
            return None

        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        state = {
            "jobId": job_id,
            "status": "cancelled",
        }
        self._local_state[job_id] = state
        await set_job_state(job_id, state)
        return state

    async def get_job_status(self, job_id: str) -> dict[str, Any] | None:
        local = self._local_state.get(job_id)
        if local:
            return local
        return await get_job_state(job_id)

    async def recover_stale_jobs(self) -> None:
        running_ids = await list_jobs_by_status("running")
        for job_id in running_ids:
            state = await get_job_state(job_id)
            if state:
                state["status"] = "failed"
                state["reason"] = "server restarted"
                await set_job_state(job_id, state)
                logger.info("Marked stale job %s as failed (server restarted)", job_id)
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/yuuzu/HanaokaYuuzu/Project/openclaw-searxng-plus && uv run pytest tests/test_job_manager.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /Users/yuuzu/HanaokaYuuzu/Project/openclaw-searxng-plus && uv run pytest tests/ -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add gateway/job_manager.py tests/test_job_manager.py
git commit -m "feat(jobs): 🚀 add async job manager with Redis state persistence

- JobManager class with create/cancel/query lifecycle
- asyncio.Task registry with max concurrent limit
- Redis state persistence (job hash + results list)
- Stale job recovery on startup (mark as failed)
- Full test coverage

Co-Authored-By: Yuuzu <yuuzu@yuuzu.net>"
```

---

## Chunk 5: Site Crawler

### Task 7: Implement site_crawler.py

**Files:**
- Create: `gateway/site_crawler.py`
- Create: `tests/test_site_crawler.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_site_crawler.py`:

```python
import asyncio

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from gateway.site_crawler import SiteCrawler


def _make_crawl_result(url: str, success: bool = True, content: str = "test content"):
    return {
        "url": url,
        "content": content if success else None,
        "markdown": content if success else None,
        "title": f"Title for {url}",
        "success": success,
        "partial": not success,
        "source": "crawl4ai",
    }


HTML_WITH_LINKS = """
<html><body>
<a href="/page2">Page 2</a>
<a href="/page3">Page 3</a>
<a href="/admin/secret">Admin</a>
</body></html>
"""


@pytest.fixture
def crawler():
    return SiteCrawler()


@pytest.mark.asyncio
class TestSiteCrawler:
    async def test_respects_max_pages(self, crawler):
        crawl_count = 0

        async def mock_crawl(url, options):
            nonlocal crawl_count
            crawl_count += 1
            return _make_crawl_result(url)

        with patch("gateway.site_crawler.crawl_url", new_callable=AsyncMock, side_effect=mock_crawl):
            with patch("gateway.site_crawler.discover_urls", new_callable=AsyncMock, return_value={
                "urls": [f"https://example.com/page{i}" for i in range(20)],
                "total": 20,
                "source": {"sitemap": 20, "links": 0},
            }):
                with patch("gateway.site_crawler.append_job_result", new_callable=AsyncMock):
                    with patch("gateway.site_crawler.set_job_state", new_callable=AsyncMock):
                        with patch("gateway.site_crawler.check_url_safety", new_callable=AsyncMock, return_value=True):
                            results = await crawler.crawl_site(
                                job_id="test_job",
                                url="https://example.com",
                                max_depth=1,
                                max_pages=5,
                            )
                            assert crawl_count <= 5

    async def test_exclude_patterns(self, crawler):
        crawled_urls = []

        async def mock_crawl(url, options):
            crawled_urls.append(url)
            return _make_crawl_result(url)

        with patch("gateway.site_crawler.crawl_url", new_callable=AsyncMock, side_effect=mock_crawl):
            with patch("gateway.site_crawler.discover_urls", new_callable=AsyncMock, return_value={
                "urls": [
                    "https://example.com/page1",
                    "https://example.com/admin/secret",
                    "https://example.com/page2",
                ],
                "total": 3,
                "source": {"sitemap": 3, "links": 0},
            }):
                with patch("gateway.site_crawler.append_job_result", new_callable=AsyncMock):
                    with patch("gateway.site_crawler.set_job_state", new_callable=AsyncMock):
                        with patch("gateway.site_crawler.check_url_safety", new_callable=AsyncMock, return_value=True):
                            await crawler.crawl_site(
                                job_id="test_job",
                                url="https://example.com",
                                max_pages=10,
                                exclude_patterns=["*/admin/*"],
                            )
                            assert not any("admin" in u for u in crawled_urls)

    async def test_include_patterns(self, crawler):
        crawled_urls = []

        async def mock_crawl(url, options):
            crawled_urls.append(url)
            return _make_crawl_result(url)

        with patch("gateway.site_crawler.crawl_url", new_callable=AsyncMock, side_effect=mock_crawl):
            with patch("gateway.site_crawler.discover_urls", new_callable=AsyncMock, return_value={
                "urls": [
                    "https://example.com/blog/post1",
                    "https://example.com/about",
                    "https://example.com/blog/post2",
                ],
                "total": 3,
                "source": {"sitemap": 3, "links": 0},
            }):
                with patch("gateway.site_crawler.append_job_result", new_callable=AsyncMock):
                    with patch("gateway.site_crawler.set_job_state", new_callable=AsyncMock):
                        with patch("gateway.site_crawler.check_url_safety", new_callable=AsyncMock, return_value=True):
                            await crawler.crawl_site(
                                job_id="test_job",
                                url="https://example.com",
                                max_pages=10,
                                include_patterns=["*/blog/*"],
                            )
                            assert all("blog" in u for u in crawled_urls)

    async def test_single_page_failure_continues(self, crawler):
        call_count = 0

        async def mock_crawl(url, options):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_crawl_result(url, success=False)
            return _make_crawl_result(url)

        with patch("gateway.site_crawler.crawl_url", new_callable=AsyncMock, side_effect=mock_crawl):
            with patch("gateway.site_crawler.discover_urls", new_callable=AsyncMock, return_value={
                "urls": ["https://example.com/fail", "https://example.com/ok"],
                "total": 2,
                "source": {"sitemap": 2, "links": 0},
            }):
                with patch("gateway.site_crawler.append_job_result", new_callable=AsyncMock):
                    with patch("gateway.site_crawler.set_job_state", new_callable=AsyncMock):
                        with patch("gateway.site_crawler.check_url_safety", new_callable=AsyncMock, return_value=True):
                            results = await crawler.crawl_site(
                                job_id="test_job",
                                url="https://example.com",
                                max_pages=10,
                            )
                            assert call_count == 2  # Both pages attempted

    async def test_timeout_stops_crawl(self, crawler):
        call_count = 0

        async def mock_crawl(url, options):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(5)  # Slow crawl
            return _make_crawl_result(url)

        with patch("gateway.site_crawler.crawl_url", new_callable=AsyncMock, side_effect=mock_crawl):
            with patch("gateway.site_crawler.discover_urls", new_callable=AsyncMock, return_value={
                "urls": [f"https://example.com/page{i}" for i in range(10)],
                "total": 10,
                "source": {"sitemap": 10, "links": 0},
            }):
                with patch("gateway.site_crawler.append_job_result", new_callable=AsyncMock):
                    with patch("gateway.site_crawler.set_job_state", new_callable=AsyncMock):
                        with patch("gateway.site_crawler.check_url_safety", new_callable=AsyncMock, return_value=True):
                            results = await crawler.crawl_site(
                                job_id="test_job",
                                url="https://example.com",
                                max_pages=10,
                                timeout_s=1,  # 1 second timeout
                            )
                            assert call_count < 10  # Should not crawl all pages

    async def test_domain_consecutive_failure_cooldown(self, crawler):
        call_count = 0

        async def mock_crawl(url, options):
            nonlocal call_count
            call_count += 1
            return _make_crawl_result(url, success=False)

        with patch("gateway.site_crawler.crawl_url", new_callable=AsyncMock, side_effect=mock_crawl):
            with patch("gateway.site_crawler.discover_urls", new_callable=AsyncMock, return_value={
                "urls": [f"https://example.com/page{i}" for i in range(10)],
                "total": 10,
                "source": {"sitemap": 10, "links": 0},
            }):
                with patch("gateway.site_crawler.append_job_result", new_callable=AsyncMock):
                    with patch("gateway.site_crawler.set_job_state", new_callable=AsyncMock):
                        with patch("gateway.site_crawler.set_domain_cooldown", new_callable=AsyncMock) as mock_cooldown:
                            with patch("gateway.site_crawler.check_url_safety", new_callable=AsyncMock, return_value=True):
                                with patch("gateway.site_crawler.settings") as mock_settings:
                                    mock_settings.site_crawl_domain_fail_limit = 3
                                    await crawler.crawl_site(
                                        job_id="test_job",
                                        url="https://example.com",
                                        max_pages=10,
                                    )
                                    mock_cooldown.assert_called()

    async def test_robots_check_filters_urls(self, crawler):
        crawled_urls = []

        async def mock_crawl(url, options):
            crawled_urls.append(url)
            return _make_crawl_result(url)

        async def mock_is_allowed(url, **kwargs):
            return "/blocked" not in url

        mock_checker = MagicMock()
        mock_checker.is_allowed = AsyncMock(side_effect=mock_is_allowed)

        with patch("gateway.site_crawler.crawl_url", new_callable=AsyncMock, side_effect=mock_crawl):
            with patch("gateway.site_crawler.discover_urls", new_callable=AsyncMock, return_value={
                "urls": [
                    "https://example.com/allowed",
                    "https://example.com/blocked",
                ],
                "total": 2,
                "source": {"sitemap": 2, "links": 0},
            }):
                with patch("gateway.site_crawler.append_job_result", new_callable=AsyncMock):
                    with patch("gateway.site_crawler.set_job_state", new_callable=AsyncMock):
                        await crawler.crawl_site(
                            job_id="test_job",
                            url="https://example.com",
                            max_pages=10,
                            respect_robots=True,
                            robots_checker=mock_checker,
                        )
                        assert "https://example.com/allowed" in crawled_urls
                        assert "https://example.com/blocked" not in crawled_urls
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/yuuzu/HanaokaYuuzu/Project/openclaw-searxng-plus && uv run pytest tests/test_site_crawler.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `gateway/site_crawler.py`**

```python
import asyncio
import logging
from collections import defaultdict
from fnmatch import fnmatch
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from urllib.parse import urljoin

from .cache import append_job_result, set_domain_cooldown, set_job_state
from .config import settings
from .crawl_client import crawl_url
from .map_client import discover_urls
from .models import CrawlOptions
from .robots import RobotsChecker
from .security import check_url_safety

logger = logging.getLogger(__name__)


def _extract_links_from_html(html: str, base_url: str) -> list[str]:
    """Extract same-domain links from HTML content."""
    try:
        soup = BeautifulSoup(html, "html.parser")
        domain = urlparse(base_url).netloc
        urls = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            absolute = urljoin(base_url, href)
            if urlparse(absolute).netloc == domain:
                urls.append(absolute)
        return urls
    except Exception:
        return []


class SiteCrawler:
    async def crawl_site(
        self,
        job_id: str,
        url: str,
        max_depth: int = 3,
        max_pages: int = 100,
        concurrency: int = 3,
        timeout_s: int = 300,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        respect_robots: bool = True,
        format: str = "markdown",
        robots_checker: RobotsChecker | None = None,
    ) -> list[dict[str, Any]]:
        sem = asyncio.Semaphore(concurrency)
        visited: set[str] = set()
        results: list[dict[str, Any]] = []
        progress = {"discovered": 0, "crawled": 0, "failed": 0}
        domain_failures: dict[str, int] = defaultdict(int)
        fail_limit = settings.site_crawl_domain_fail_limit

        if respect_robots and robots_checker is None:
            robots_checker = RobotsChecker()

        crawl_options = CrawlOptions(
            maxDepth=1,
            maxPages=1,
            timeoutMs=15000,
            concurrency=1,
            onlyMainContent=True,
            bypassCache=False,
            respectRobots=False,  # We handle robots at site_crawler level
        )

        # Discover initial URLs (depth 0)
        discovery = await discover_urls(url, include_patterns=include_patterns, use_sitemap=True)
        seed_urls = discovery.get("urls", [])
        if url not in seed_urls:
            seed_urls.insert(0, url)
        seed_urls = self._filter_urls(seed_urls, include_patterns, exclude_patterns)

        # SSRF check on seed URLs
        safe_seeds = []
        for u in seed_urls:
            if await check_url_safety(u):
                safe_seeds.append(u)
        seed_urls = safe_seeds

        progress["discovered"] = len(seed_urls)
        await self._update_progress(job_id, progress)

        # BFS queue: list of (url, depth) tuples
        queue: list[tuple[str, int]] = [(u, 0) for u in seed_urls]

        async def _crawl_one(target_url: str) -> dict[str, Any] | None:
            async with sem:
                if len(results) >= max_pages:
                    return None

                domain = urlparse(target_url).netloc

                # Domain cooldown check
                if domain_failures[domain] >= fail_limit:
                    return None

                # robots.txt check
                if respect_robots and robots_checker:
                    if not await robots_checker.is_allowed(target_url):
                        logger.debug("robots.txt blocks %s", target_url)
                        return None

                try:
                    result = await crawl_url(target_url, crawl_options)
                    item = {
                        "url": target_url,
                        "title": result.get("title"),
                        "content": result.get("content") or result.get("markdown"),
                        "html": result.get("html"),
                        "success": result.get("success", False),
                    }

                    if item["success"]:
                        progress["crawled"] += 1
                        domain_failures[domain] = 0  # Reset on success
                    else:
                        progress["failed"] += 1
                        domain_failures[domain] += 1
                        if domain_failures[domain] >= fail_limit:
                            await set_domain_cooldown(domain)
                            logger.warning("Domain %s cooled down after %d failures", domain, fail_limit)

                    results.append(item)
                    # Store without html in job results
                    store_item = {k: v for k, v in item.items() if k != "html"}
                    await append_job_result(job_id, store_item)
                    await self._update_progress(job_id, progress)
                    return item

                except Exception:
                    progress["failed"] += 1
                    domain_failures[domain] += 1
                    if domain_failures[domain] >= fail_limit:
                        await set_domain_cooldown(domain)
                    logger.debug("Failed to crawl %s", target_url, exc_info=True)
                    await self._update_progress(job_id, progress)
                    return None

        try:
            async with asyncio.timeout(timeout_s):
                while queue and len(results) < max_pages:
                    target_url, depth = queue.pop(0)

                    if target_url in visited:
                        continue
                    visited.add(target_url)

                    item = await _crawl_one(target_url)

                    # BFS: extract new URLs from crawled HTML if depth allows
                    if item and item.get("success") and depth < max_depth:
                        html = item.get("html") or item.get("content") or ""
                        if html:
                            new_urls = _extract_links_from_html(html, target_url)
                            new_urls = self._filter_urls(new_urls, include_patterns, exclude_patterns)
                            for new_url in new_urls:
                                if new_url not in visited and await check_url_safety(new_url):
                                    queue.append((new_url, depth + 1))
                                    progress["discovered"] += 1
                            await self._update_progress(job_id, progress)

        except asyncio.TimeoutError:
            logger.warning("Site crawl timed out for job %s after %ds", job_id, timeout_s)

        return results

    def _filter_urls(
        self,
        urls: list[str],
        include_patterns: list[str] | None,
        exclude_patterns: list[str] | None,
    ) -> list[str]:
        filtered = urls

        if include_patterns:
            filtered = [u for u in filtered if any(fnmatch(u, p) for p in include_patterns)]

        if exclude_patterns:
            filtered = [u for u in filtered if not any(fnmatch(u, p) for p in exclude_patterns)]

        return filtered

    async def _update_progress(self, job_id: str, progress: dict) -> None:
        state = {
            "jobId": job_id,
            "status": "running",
            "progress": progress.copy(),
        }
        await set_job_state(job_id, state)
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/yuuzu/HanaokaYuuzu/Project/openclaw-searxng-plus && uv run pytest tests/test_site_crawler.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /Users/yuuzu/HanaokaYuuzu/Project/openclaw-searxng-plus && uv run pytest tests/ -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add gateway/site_crawler.py tests/test_site_crawler.py
git commit -m "feat(crawler): 🚀 add BFS site crawler with pattern filtering

- SiteCrawler class with crawl_site() method
- BFS traversal with max_pages and max_depth limits
- include/exclude pattern filtering (fnmatch glob)
- robots.txt integration via RobotsChecker
- Concurrent crawling with asyncio.Semaphore
- Progress tracking to Redis
- Single-page failure tolerance
- Full test coverage

Co-Authored-By: Yuuzu <yuuzu@yuuzu.net>"
```

---

## Chunk 6: API Routes + Search Integration

### Task 8: Add `/map` and `/crawl/site` routes

**Files:**
- Modify: `gateway/app.py`

- [ ] **Step 1: Add imports and initialize JobManager in lifespan**

Update imports in `gateway/app.py` (add `urlparse` at module level, add new model imports):

```python
from urllib.parse import urlparse

from .config import settings
from .job_manager import JobManager
from .map_client import discover_urls
from .models import (
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
    SiteCrawlStatusResponse,
    CrawlProgress,
    SiteCrawlResultItem,
)
from .robots import RobotsChecker
from .site_crawler import SiteCrawler
from .cache import (
    close_redis,
    get_cached_results,
    get_job_state,
    get_job_results,
    get_job_result_count,
    set_cached_results,
)
```

Update lifespan:

```python
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
```

- [ ] **Step 2: Add `POST /map` route**

```python
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
```

- [ ] **Step 3: Add `POST /crawl/site` route**

```python
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
```

- [ ] **Step 4: Add `GET /crawl/site/{job_id}` route**

```python
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
```

- [ ] **Step 5: Add `DELETE /crawl/site/{job_id}` route**

```python
@app.delete("/crawl/site/{job_id}", response_model=JobCancelResponse)
async def cancel_crawl_site(job_id: str, request: Request):
    _authorize_request(request)

    assert _job_manager is not None

    # Check if job exists in Redis
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
```

- [ ] **Step 6: Run existing tests**

Run: `cd /Users/yuuzu/HanaokaYuuzu/Project/openclaw-searxng-plus && uv run pytest tests/ -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add gateway/app.py
git commit -m "feat(api): 🚀 add /map, /crawl/site endpoints with job management

- POST /map for URL discovery
- POST /crawl/site for async site crawl
- GET /crawl/site/{job_id} with pagination
- DELETE /crawl/site/{job_id} with 404/409 handling
- JobManager + RobotsChecker initialized in lifespan
- Stale job recovery on startup

Co-Authored-By: Yuuzu <yuuzu@yuuzu.net>"
```

### Task 9: Integrate needMap + needSiteCrawl into /search

**Files:**
- Modify: `gateway/app.py`

- [ ] **Step 1: Update the search function to handle new flags**

In the `/search` route handler, after the enrichment section (`# --- Optional enrichment ---`), add map and site crawl logic:

```python
    # --- Optional enrichment ---
    if req.needCrawl and crawl_options is not None:
        top_results = await crawl_results_batch(top_results, crawl_options)

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
```

- [ ] **Step 2: Update result building to include new fields**

Update the result building loop:

```python
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
```

- [ ] **Step 3: Exclude siteCrawlJobId from cache**

Before cache storage, strip `siteCrawlJobId`:

```python
    cache_results = []
    for r in results:
        d = r.model_dump()
        d.pop("siteCrawlJobId", None)
        cache_results.append(d)

    cache_payload = {
        "results": cache_results,
        "total_found": total_found,
    }
```

- [ ] **Step 4: Run full test suite**

Run: `cd /Users/yuuzu/HanaokaYuuzu/Project/openclaw-searxng-plus && uv run pytest tests/ -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add gateway/app.py
git commit -m "feat(search): 🚀 integrate needMap and needSiteCrawl into /search

- needMap: discover related URLs per domain in search results
- needSiteCrawl: trigger async site crawl jobs per domain
- siteCrawlJobId excluded from search result cache
- Cache key includes needMap, needSiteCrawl, format flags

Co-Authored-By: Yuuzu <yuuzu@yuuzu.net>"
```

### Task 10: Add API integration tests

**Files:**
- Modify: `tests/test_api.py`

- [ ] **Step 1: Add tests for new endpoints**

Append to `tests/test_api.py` (also add `MagicMock` to the existing `from unittest.mock import` line if not present):

```python
from unittest.mock import MagicMock  # add to existing imports if missing


@pytest.mark.asyncio
class TestMapEndpoint:
    async def test_requires_auth(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/map", json={"url": "https://example.com"})
            assert resp.status_code == 401

    async def test_map_success(self):
        with patch("gateway.app.discover_urls", new_callable=AsyncMock, return_value={
            "urls": ["https://example.com/page1"],
            "total": 1,
            "source": {"sitemap": 1, "links": 0},
        }):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/map",
                    json={"url": "https://example.com"},
                    headers=HEADERS,
                )
                assert resp.status_code == 200
                data = resp.json()
                assert "urls" in data
                assert "total" in data
                assert "source" in data


@pytest.mark.asyncio
class TestCrawlSiteEndpoint:
    async def test_requires_auth(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/crawl/site", json={"url": "https://example.com"})
            assert resp.status_code == 401

    async def test_get_nonexistent_job(self):
        with patch("gateway.app._job_manager") as mock_jm:
            mock_jm.get_job_status = AsyncMock(return_value=None)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/crawl/site/job_nonexistent",
                    headers=HEADERS,
                )
                assert resp.status_code == 404

    async def test_delete_nonexistent_job(self):
        with patch("gateway.app._job_manager") as mock_jm:
            mock_jm.get_job_status = AsyncMock(return_value=None)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.delete(
                    "/crawl/site/job_nonexistent",
                    headers=HEADERS,
                )
                assert resp.status_code == 404

    async def test_delete_completed_job_returns_409(self):
        with patch("gateway.app._job_manager") as mock_jm:
            mock_jm.get_job_status = AsyncMock(return_value={"status": "completed", "jobId": "job_123"})
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.delete(
                    "/crawl/site/job_123",
                    headers=HEADERS,
                )
                assert resp.status_code == 409


@pytest.mark.asyncio
class TestCrawlSiteSuccess:
    async def test_create_site_crawl_job(self):
        with patch("gateway.app._job_manager") as mock_jm:
            mock_jm.create_job = AsyncMock(return_value="job_test123")
            mock_jm.get_local_state = MagicMock(return_value={
                "status": "running",
                "startedAt": "2026-03-14T00:00:00Z",
            })
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/crawl/site",
                    json={"url": "https://example.com"},
                    headers=HEADERS,
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["jobId"] == "job_test123"
                assert data["status"] == "running"


@pytest.mark.asyncio
class TestSearchIntegration:
    async def test_search_with_need_map(self, mock_searxng, mock_cache_miss):
        with patch("gateway.app.discover_urls", new_callable=AsyncMock, return_value={
            "urls": ["https://docs.python.org/3/library/"],
            "total": 1,
            "source": {"sitemap": 1, "links": 0},
        }):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/search",
                    json={"q": "python", "topK": 3, "needMap": True},
                    headers=HEADERS,
                )
                assert resp.status_code == 200
                data = resp.json()
                assert len(data["results"]) > 0

    async def test_search_with_need_site_crawl(self, mock_searxng, mock_cache_miss):
        with patch("gateway.app._job_manager") as mock_jm:
            mock_jm.create_job = AsyncMock(return_value="job_search123")
            with patch("gateway.app._site_crawler") as mock_sc:
                with patch("gateway.app._robots_checker"):
                    transport = ASGITransport(app=app)
                    async with AsyncClient(transport=transport, base_url="http://test") as client:
                        resp = await client.post(
                            "/search",
                            json={"q": "python", "topK": 3, "needSiteCrawl": True},
                            headers=HEADERS,
                        )
                        assert resp.status_code == 200
                        data = resp.json()
                        # At least one result should have a siteCrawlJobId
                        has_job = any(r.get("siteCrawlJobId") for r in data["results"])
                        assert has_job
```

- [ ] **Step 2: Run all tests**

Run: `cd /Users/yuuzu/HanaokaYuuzu/Project/openclaw-searxng-plus && uv run pytest tests/ -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_api.py
git commit -m "test(api): ✅ add integration tests for /map, /crawl/site, search integration

- Map endpoint auth and success tests
- Crawl/site 404 and 409 error handling tests
- Search with needMap integration test

Co-Authored-By: Yuuzu <yuuzu@yuuzu.net>"
```

---

## Chunk 7: Crawl Client Enhancement + Skill Update

### Task 11: Add format + respectRobots to crawl_client

**Files:**
- Modify: `gateway/crawl_client.py`

- [ ] **Step 1: Add robots check to `crawl_url`**

At the top of `crawl_url`, after the existing SSRF check, add:

```python
    # Optional robots.txt check
    if options.respectRobots:
        from .robots import RobotsChecker
        checker = RobotsChecker()
        if not await checker.is_allowed(url):
            return {
                "url": url,
                "content": None,
                "markdown": None,
                "title": None,
                "success": False,
                "partial": True,
                "source": "crawl4ai",
            }
```

- [ ] **Step 2: Add format selection to `crawl_url` return**

After the existing content extraction and sanitization logic (where `crawl_url` builds the success return dict), add format selection. Modify the return dict construction:

```python
def _select_format(content: str | None, markdown: str | None, html: str | None, format: str) -> str | None:
    """Select content based on requested output format."""
    if format == "html":
        return html or content
    elif format == "text":
        # Strip markdown formatting for plain text
        return content  # content is already sanitized plain-ish text
    else:  # "markdown" (default)
        return markdown or content
```

Add `format` parameter to `crawl_url` signature:

```python
async def crawl_url(url: str, options: CrawlOptions, format: str = "markdown") -> dict[str, Any]:
```

In the success return path, apply format selection:

```python
                selected_content = _select_format(
                    sanitized_content, sanitized_markdown, None, format
                )

                return {
                    "url": url,
                    "content": selected_content,
                    "markdown": sanitized_markdown,
                    "html": None,  # raw HTML from Crawl4AI if available
                    "title": title,
                    "success": True,
                    "partial": partial,
                    "source": "crawl4ai",
                }
```

- [ ] **Step 3: Run full test suite**

Run: `cd /Users/yuuzu/HanaokaYuuzu/Project/openclaw-searxng-plus && uv run pytest tests/ -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add gateway/crawl_client.py
git commit -m "feat(crawl): 🚀 add format selection and respectRobots to crawl_url

- Add _select_format() for markdown/text/html output
- Add robots.txt check before crawling
- Pass format parameter through crawl pipeline

Co-Authored-By: Yuuzu <yuuzu@yuuzu.net>"
```

### Task 12: Update yuuzu-search skill

**Files:**
- Modify: `skill/yuuzu-search/SKILL.md`

- [ ] **Step 1: Read current skill**

Read `skill/yuuzu-search/SKILL.md` to understand current structure.

- [ ] **Step 2: Update skill documentation**

Use `/skill-creator` to update the skill with new endpoint documentation:
- Add `/map` endpoint usage
- Add `/crawl/site` endpoint usage (POST, GET, DELETE)
- Add `needMap` and `needSiteCrawl` flags to `/search` examples
- Add `format` parameter documentation
- Add `respectRobots` parameter documentation

- [ ] **Step 3: Commit**

```bash
git add skill/yuuzu-search/
git commit -m "docs(skill): 📚 update yuuzu-search skill with new endpoints

- Add /map URL discovery endpoint
- Add /crawl/site async site crawl endpoints
- Add needMap, needSiteCrawl, format parameters
- Update search examples

Co-Authored-By: Yuuzu <yuuzu@yuuzu.net>"
```

### Task 13: Final verification

- [ ] **Step 1: Run full test suite**

Run: `cd /Users/yuuzu/HanaokaYuuzu/Project/openclaw-searxng-plus && uv run pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 2: Verify imports are clean**

Run: `cd /Users/yuuzu/HanaokaYuuzu/Project/openclaw-searxng-plus && uv run python -c "from gateway.app import app; print('OK')"``
Expected: `OK`

- [ ] **Step 3: Review git log**

Run: `git log --oneline -15`
Verify all commits are present and well-structured.
