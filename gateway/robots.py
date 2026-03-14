import logging
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
