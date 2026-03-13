# SearXNG++ for OpenClaw — Design Document

## Overview

A production-minded search backend for OpenClaw that wraps SearXNG as an upstream
meta-search aggregator and adds normalization, deduplication, hybrid reranking, optional
content enrichment, caching, and security hardening.

This revision adds **Crawl4AI support** behind the gateway with one Bearer token auth model.

## Architecture

```
OpenClaw  ──POST /search,/crawl──▶  Gateway (FastAPI)
                                        │
                    ┌───────────────────┼───────────────────┐
                    ▼                   ▼                   ▼
                 SearXNG              Redis          Crawl4AI Service
                (upstream)            (cache)          (internal API)
                    │                   │
             70+ engines      query/content cache
```

### Components

| Component | Technology | Purpose |
|-----------|-----------|---------|
| SearXNG | Docker (pinned `2026.3.6-0716de6bc`) | Meta-search aggregation across 70+ engines |
| Gateway | Python 3.12 + FastAPI + uvicorn | Auth, normalization, dedup, rerank, API orchestration |
| Redis | Docker (`redis:7.4-alpine`) | Query cache, content cache, domain cooldown |
| Crawl4AI Service | Docker (`unclecode/crawl4ai:0.8.0`) | Deep crawl/content extraction via internal `/crawl` API |
| Legacy Content Fetcher | httpx + readability-lxml + playwright (optional) | Fallback extraction when requested |

## Request Flow

1. **Auth & Rate Limit** — verify Bearer token, enforce per-IP RPM limit
2. **Cache Check** — SHA-256 keyed query cache in Redis
3. **SearXNG Query** — fetch pages 1-2 for broader coverage
4. **Normalize** — canonical URLs, strip tracking params, parse dates
5. **Deduplicate** — URL-exact + title-fuzzy
6. **Rerank** — weighted lexical/semantic/quality/freshness score
7. **Optional enrichment**
   - `needCrawl=true`: gateway calls internal Crawl4AI service
   - `needContent=true` and crawl misses: fallback to legacy fetch pipeline
   - `needCrawl=false, needContent=true`: legacy fetch pipeline only
8. **Sanitize** — strip HTML/injection artifacts, truncate
9. **Cache Store** — includes `needCrawl` + crawl options in cache key
10. **Return** — ordered results with timing

## Security Hardening

- **One auth model** — Bearer token required on both `/search` and `/crawl`
- **No docker.sock mount** — compose does not bind Docker socket
- **Pinned image tags** — avoid floating `latest`
- **Internal networking** — compose services communicate on private bridge
- **Rate limiting** — in-memory sliding-window per client IP
- **SSRF protection** — block private/reserved CIDRs, loopback, unsafe schemes
- **Content sanitization** — strip HTML, filter prompt-injection artifacts

## Tradeoffs

| Decision | Chosen | Alternative | Rationale |
|----------|--------|-------------|-----------|
| Crawl integration | Gateway -> internal Crawl4AI service | Direct library embedding in gateway | Keeps gateway focused and isolates browser-heavy crawl runtime |
| Legacy content fetcher | Retained as fallback | Full replacement | Preserves backward compatibility and resilience |
| Jina Reader | Not included | Add extra external fetch stage | Avoided by explicit requirement |

## API Contract

### `POST /search`

Authorization: `Bearer <token>`

```json
{
  "q": "latest n8n release notes",
  "topK": 10,
  "needContent": false,
  "freshness": "any",
  "needCrawl": true,
  "crawlMaxDepth": 1,
  "crawlMaxPages": 1,
  "crawlTimeoutMs": 15000,
  "crawlConcurrency": 3,
  "crawlOnlyMainContent": true,
  "crawlBypassCache": false
}
```

`needCrawl` and crawl option fields are optional with safe defaults, so existing `/search`
clients remain compatible without request changes.

### `POST /crawl`

Authorization: `Bearer <token>`

```json
{
  "url": "https://example.com/article",
  "maxDepth": 1,
  "maxPages": 1,
  "timeoutMs": 15000,
  "onlyMainContent": true,
  "bypassCache": false
}
```

```json
{
  "result": {
    "url": "https://example.com/article",
    "content": "...",
    "title": "...",
    "markdown": "...",
    "success": true,
    "partial": false,
    "source": "crawl4ai"
  },
  "timing_ms": 320.4
}
```

## File Structure

```
searxng-plus/
├── docs/DESIGN.md
├── gateway/
│   ├── app.py              # FastAPI application
│   ├── config.py           # Pydantic settings
│   ├── models.py           # Request/response models
│   ├── crawl_client.py     # Internal Crawl4AI HTTP client
│   ├── searxng_client.py   # SearXNG HTTP client
│   ├── normalizer.py       # URL/result normalization
│   ├── deduplicator.py     # Dedup logic
│   ├── reranker.py         # Hybrid reranking
│   ├── content_fetcher.py  # Legacy content fetch fallback
│   ├── cache.py            # Redis cache layer
│   ├── security.py         # Auth, rate-limit, SSRF
│   └── sanitizer.py        # Content sanitization
├── tests/
├── config/searxng/settings.yml
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── .env.example
```
