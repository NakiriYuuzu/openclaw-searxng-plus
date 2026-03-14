from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # SearXNG upstream
    searxng_url: str = "http://localhost:8888"
    searxng_timeout: float = 6.0

    # Crawl4AI internal service
    crawl_service_url: str = "http://localhost:11235"
    crawl_service_path: str = "/crawl"
    crawl_service_timeout: float = 45.0
    crawl_max_content_length: int = 100000
    crawl_max_concurrent: int = 3

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl: int = 3600
    content_cache_ttl: int = 86400
    domain_cooldown_ttl: int = 300

    # Authentication — MUST be set via GATEWAY_AUTH_TOKEN env var
    auth_token: str = Field(..., description="Auth token (set GATEWAY_AUTH_TOKEN env var)")

    # Rate limiting (requests per minute per client)
    rate_limit_rpm: int = 60

    # Content fetching
    content_fetch_timeout: float = 8.0
    max_content_length: int = 50000
    enable_browser_fallback: bool = False

    # Result limits
    max_results: int = 20
    default_top_k: int = 10

    # Reranker weights
    weight_lexical: float = 0.25
    weight_semantic: float = 0.20
    weight_quality: float = 0.20
    weight_freshness: float = 0.15
    weight_language: float = 0.20

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

    model_config = {"env_prefix": "GATEWAY_", "env_file": ".env"}


settings = Settings()
