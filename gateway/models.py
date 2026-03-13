from enum import Enum
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


class Freshness(str, Enum):
    any = "any"
    day = "day"
    week = "week"
    month = "month"


class CrawlOptions(BaseModel):
    maxDepth: int = Field(default=1, ge=1, le=5)
    maxPages: int = Field(default=1, ge=1, le=20)
    timeoutMs: int = Field(default=15000, ge=1000, le=120000)
    concurrency: int = Field(default=3, ge=1, le=10)
    onlyMainContent: bool = True
    bypassCache: bool = False

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

    # Crawl4AI enrichment (optional)
    needCrawl: bool = False
    crawlMaxDepth: int = Field(default=1, ge=1, le=5)
    crawlMaxPages: int = Field(default=1, ge=1, le=20)
    crawlTimeoutMs: int = Field(default=15000, ge=1000, le=120000)
    crawlConcurrency: int = Field(default=3, ge=1, le=10)
    crawlOnlyMainContent: bool = True
    crawlBypassCache: bool = False

    def crawl_options(self) -> CrawlOptions:
        return CrawlOptions(
            maxDepth=self.crawlMaxDepth,
            maxPages=self.crawlMaxPages,
            timeoutMs=self.crawlTimeoutMs,
            concurrency=self.crawlConcurrency,
            onlyMainContent=self.crawlOnlyMainContent,
            bypassCache=self.crawlBypassCache,
        )


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    content: str | None = None
    score: float
    source: str
    content_partial: bool = False


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
