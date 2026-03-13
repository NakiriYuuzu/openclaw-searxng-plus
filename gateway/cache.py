import hashlib
import json
import logging
from typing import Optional

import redis.asyncio as redis

from .config import settings

logger = logging.getLogger(__name__)

_pool: Optional[redis.Redis] = None


async def get_redis() -> redis.Redis:
    global _pool
    if _pool is None:
        _pool = redis.from_url(settings.redis_url, decode_responses=True)
    return _pool


def _key(prefix: str, *parts: str) -> str:
    raw = ":".join(parts)
    h = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"oc:{prefix}:{h}"


def _search_cache_key(
    query: str,
    freshness: str,
    top_k: int,
    need_content: bool,
    need_crawl: bool = False,
    crawl_options_key: str = "",
) -> str:
    parts = [query.lower().strip(), freshness, str(top_k), str(need_content), str(need_crawl)]
    if need_crawl:
        parts.append(crawl_options_key)
    return _key("search", *parts)


# ---------------------------------------------------------------------------
# Query result cache
# ---------------------------------------------------------------------------
async def get_cached_results(
    query: str,
    freshness: str,
    top_k: int,
    need_content: bool = False,
    need_crawl: bool = False,
    crawl_options_key: str = "",
) -> Optional[dict]:
    try:
        r = await get_redis()
        data = await r.get(
            _search_cache_key(query, freshness, top_k, need_content, need_crawl, crawl_options_key)
        )
        return json.loads(data) if data else None
    except Exception:
        logger.debug("Cache read miss/error", exc_info=True)
        return None


async def set_cached_results(
    query: str,
    freshness: str,
    top_k: int,
    payload: dict,
    need_content: bool = False,
    need_crawl: bool = False,
    crawl_options_key: str = "",
) -> None:
    try:
        r = await get_redis()
        await r.setex(
            _search_cache_key(query, freshness, top_k, need_content, need_crawl, crawl_options_key),
            settings.cache_ttl,
            json.dumps(payload),
        )
    except Exception:
        logger.debug("Cache write error", exc_info=True)


# ---------------------------------------------------------------------------
# Content cache
# ---------------------------------------------------------------------------
async def get_cached_content(url: str) -> Optional[tuple[str | None, bool]]:
    try:
        r = await get_redis()
        data = await r.get(_key("content", url))
        if data:
            obj = json.loads(data)
            return obj["content"], obj["partial"]
        return None
    except Exception:
        return None


async def set_cached_content(url: str, content: str | None, partial: bool) -> None:
    try:
        r = await get_redis()
        await r.setex(
            _key("content", url),
            settings.content_cache_ttl,
            json.dumps({"content": content, "partial": partial}),
        )
    except Exception:
        logger.debug("Content cache write error", exc_info=True)


# ---------------------------------------------------------------------------
# Domain cooldown
# ---------------------------------------------------------------------------
async def is_domain_cooled_down(domain: str) -> bool:
    try:
        r = await get_redis()
        return (await r.exists(f"oc:cooldown:{domain}")) > 0
    except Exception:
        return False


async def set_domain_cooldown(domain: str) -> None:
    try:
        r = await get_redis()
        await r.setex(f"oc:cooldown:{domain}", settings.domain_cooldown_ttl, "1")
    except Exception:
        pass


async def close_redis() -> None:
    global _pool
    if _pool:
        await _pool.aclose()
        _pool = None
