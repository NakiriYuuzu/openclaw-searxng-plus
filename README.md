# openclaw-searxng-plus

A self-hosted search and crawl gateway for OpenClaw.

It combines:
- **SearXNG** for metasearch
- **FastAPI gateway** for auth, reranking, caching, and orchestration
- **Crawl4AI** for `/crawl` and optional `needCrawl` enrichment on `/search`
- **Redis** for cache and cooldown state

The deployed gateway supports both:
- `POST /search`
- `POST /crawl`

For public/private endpoint routing, keep the actual base URL in environment variables instead of hardcoding it into shared docs.

## Why this repo exists

This repo turns raw SearXNG results into something more useful for agent workflows:
- one Bearer token auth model
- normalized and deduplicated results
- reranked output for agent consumption
- optional content enrichment
- optional crawl enrichment with Crawl4AI
- deployable behind Cloudflare

## Features

- **`/search`** with:
  - `q`, `topK`, `freshness`, `needContent`
  - `needCrawl=true` for automatic crawl enrichment on top results
- **`/crawl`** for direct page extraction
- **Single auth token** across search and crawl
- **Redis-backed caching**
- **Internal-service architecture**:
  - gateway
  - searxng
  - redis
  - crawl4ai
- **Cloudflare-friendly deployment compose** for production hosts already using tunnel networks

## API overview

### `POST /search`

```json
{
  "q": "OpenClaw ACP runtime",
  "topK": 5,
  "freshness": "week",
  "needContent": false,
  "needCrawl": true,
  "crawlMaxDepth": 1,
  "crawlMaxPages": 1,
  "crawlTimeoutMs": 12000,
  "crawlOnlyMainContent": true
}
```

### `POST /crawl`

```json
{
  "url": "https://docs.openclaw.ai",
  "maxDepth": 1,
  "maxPages": 1,
  "timeoutMs": 12000,
  "onlyMainContent": true
}
```

## Local development

### Requirements
- Python 3.12+
- Docker + Docker Compose
- `uv` recommended

### Config
Copy `.env.example` to `.env` and set at least:

```bash
GATEWAY_AUTH_TOKEN=your-secure-token
```

### Run tests

```bash
.venv/bin/pytest -q
```

### Start locally

```bash
docker compose up -d --build
```

Local services:
- gateway: `127.0.0.1:8000`
- searxng: `127.0.0.1:8888`
- crawl4ai: `127.0.0.1:11235`

## Production deployment

This repo includes two compose files:

- `docker-compose.yml`
  - local/dev usage
  - binds gateway on host port `8000`
- `docker-compose.deploy.yml`
  - production-style deployment for hosts already using `cloudflare_default`
  - keeps gateway internal to Docker networks
  - avoids host port conflicts with existing services

For tunnel-based production hosts, prefer:

```bash
docker compose -f docker-compose.deploy.yml up -d --build
```

## Skill sync

This repo also includes the synced `yuuzu-search` skill:

- `skill/yuuzu-search/SKILL.md`
- `skill/yuuzu-search/scripts/search_request.sh`
- `skill/yuuzu-search/references/runbook.md`

The helper script reads:
- `GATEWAY_AUTH_TOKEN`
- `YUUZU_SEARCH_BASE_URL`

from the shell environment by default.

## Example curl

### Search

```bash
export YUUZU_SEARCH_BASE_URL="https://your-search-gateway.example.com"

curl -sS "$YUUZU_SEARCH_BASE_URL/search" \
  -H "Authorization: Bearer $GATEWAY_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"q":"OpenClaw ACP runtime","topK":3,"freshness":"month","needCrawl":true}'
```

### Crawl

```bash
curl -sS "$YUUZU_SEARCH_BASE_URL/crawl" \
  -H "Authorization: Bearer $GATEWAY_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://docs.openclaw.ai","maxDepth":1,"maxPages":1,"timeoutMs":12000,"onlyMainContent":true}'
```

## Docs

- Design: `docs/DESIGN.md`
- Operations notes: `skill/yuuzu-search/references/runbook.md`

## License

See repository license and upstream dependency licenses.
