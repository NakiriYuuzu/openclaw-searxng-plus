import hashlib
import json
import logging
from typing import Optional

import redis.asyncio as aioredis

from .config import settings

logger = logging.getLogger(__name__)

_pool: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    global _pool
    if _pool is None:
        _pool = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_keepalive=True,
        )
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


async def close_redis() -> None:
    global _pool
    if _pool:
        await _pool.aclose()
        _pool = None
