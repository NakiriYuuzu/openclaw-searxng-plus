from enum import Enum
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


class Freshness(str, Enum):
    any = "any"
    day = "day"
    week = "week"
    month = "month"


class OutputFormat(str, Enum):
    markdown = "markdown"
    text = "text"
    html = "html"


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


class SearchRequest(BaseModel):
    q: str = Field(..., min_length=1, max_length=500)
    topK: int = Field(default=10, ge=1, le=50)
    needContent: bool = False
    freshness: Freshness = Freshness.any
    lang: str | None = Field(default=None, max_length=10)

    # Crawl4AI enrichment (optional)
    needCrawl: bool = False
    crawlMaxDepth: int = Field(default=1, ge=1, le=5)
    crawlMaxPages: int = Field(default=1, ge=1, le=20)
    crawlTimeoutMs: int = Field(default=15000, ge=1000, le=120000)
    crawlConcurrency: int = Field(default=3, ge=1, le=10)
    crawlOnlyMainContent: bool = True
    crawlBypassCache: bool = False
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

    # Content cleaning
    stripLinks: bool = False

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


class SearchResponse(BaseModel):
    results: list[SearchResult]
    timing_ms: float
    query: str
    total_found: int


class CrawlRequest(BaseModel):
    url: str = Field(..., min_length=5, max_length=2048)
    maxDepth: int = Field(default=1, ge=1, le=5)
    maxPages: int = Field(default=1, ge=1, le=20)
    timeoutMs: int = Field(default=15000, ge=1000, le=120000)
    onlyMainContent: bool = True
    bypassCache: bool = False
    format: OutputFormat = OutputFormat.markdown
    respectRobots: bool = True
    stripLinks: bool = False

    @field_validator("url")
    @classmethod
    def validate_http_url(cls, value: str) -> str:
        url = value.strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("url must be a valid http/https URL")
        return url

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


class CrawlResult(BaseModel):
    url: str
    content: str | None = None
    title: str | None = None
    markdown: str | None = None
    success: bool
    partial: bool
    source: str = "crawl4ai"


class CrawlResponse(BaseModel):
    result: CrawlResult
    timing_ms: float


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
