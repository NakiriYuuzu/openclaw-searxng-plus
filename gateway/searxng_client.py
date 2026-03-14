import logging
from typing import Any

import httpx

from .config import settings

logger = logging.getLogger(__name__)


async def query_searxng(
    q: str,
    time_range: str | None = None,
    pageno: int = 1,
    categories: str = "general",
    language: str | None = None,
) -> list[dict[str, Any]]:
    """Query SearXNG and return raw result list."""
    params: dict[str, Any] = {
        "q": q,
        "format": "json",
        "categories": categories,
        "pageno": pageno,
    }
    if time_range:
        params["time_range"] = time_range
    if language:
        params["language"] = language

    try:
        async with httpx.AsyncClient(timeout=settings.searxng_timeout) as client:
            resp = await client.get(
                f"{settings.searxng_url}/search",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("results", [])
    except httpx.TimeoutException:
        logger.warning("SearXNG timeout for query: %s", q)
        return []
    except httpx.HTTPStatusError as exc:
        logger.warning("SearXNG HTTP %d for query: %s", exc.response.status_code, q)
        return []
    except Exception:
        logger.exception("SearXNG request failed for query: %s", q)
        return []
