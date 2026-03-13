from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # SearXNG upstream
    searxng_url: str = "http://localhost:8888"
    searxng_timeout: float = 6.0

    # Crawl4AI internal service
    crawl_service_url: str = "http://localhost:11235"
    crawl_service_path: str = "/crawl"
    crawl_service_timeout: float = 20.0
    crawl_max_content_length: int = 100000
    crawl_max_concurrent: int = 3

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl: int = 3600
    content_cache_ttl: int = 86400
    domain_cooldown_ttl: int = 300

    # Authentication
    auth_token: str = "changeme"

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
    weight_lexical: float = 0.30
    weight_semantic: float = 0.25
    weight_quality: float = 0.25
    weight_freshness: float = 0.20

    model_config = {"env_prefix": "GATEWAY_", "env_file": ".env"}


settings = Settings()
