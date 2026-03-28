# Runbook: search.yuuzu.net

## Topology
- Public endpoint: `https://search.yuuzu.net`
- Backend: oracle-my `openclaw-searxng-plus`
- Auth: `Authorization: Bearer <GATEWAY_AUTH_TOKEN>`
- Components: FastAPI gateway + SearXNG + Redis + Crawl4AI

## API Contract

### GET /health
- Response: `200 {"status":"ok"}`

### POST /search
Body fields:
- `q` string (1..500) required
- `topK` int (1..50), default 10
- `needContent` bool, default false
- `needCrawl` bool, default false — deep crawl via Crawl4AI
- `needMap` bool, default false — URL discovery per domain
- `needSiteCrawl` bool, default false — async site crawl per domain
- `freshness` enum: `any|day|week|month`, default `any`
- `lang` string, default auto-detect (`en`, `zh-TW`)
- `format` enum: `markdown|text|html`, default `markdown`
- `stripLinks` bool, default false
- `crawlMaxDepth` int (1..5), default 1
- `crawlMaxPages` int (1..20), default 1
- `crawlTimeoutMs` int (1000..120000), default 15000
- `crawlConcurrency` int (1..10), default 3
- `crawlOnlyMainContent` bool, default true
- `crawlBypassCache` bool, default false
- `crawlRespectRobots` bool, default true
- `siteCrawlMaxDepth` int (1..10), default 1
- `siteCrawlMaxPages` int (1..500), default 5
- `siteCrawlConcurrency` int (1..10), default 3
- `siteCrawlIncludePatterns` string[], default []
- `siteCrawlExcludePatterns` string[], default []

Response:
```json
{
  "results": [
    {
      "title": "...",
      "url": "...",
      "snippet": "...",
      "content": "...",
      "score": 0.85,
      "source": "google",
      "content_partial": false,
      "relatedUrls": ["..."],
      "siteCrawlJobId": "job_xxxxx"
    }
  ],
  "timing_ms": 1234.5,
  "query": "...",
  "total_found": 20
}
```

### POST /crawl
Body fields:
- `url` string (5..2048) required — must be http/https
- `maxDepth` int (1..5), default 1
- `maxPages` int (1..20), default 1
- `timeoutMs` int (1000..120000), default 15000
- `onlyMainContent` bool, default true
- `bypassCache` bool, default false
- `format` enum: `markdown|text|html`, default `markdown`
- `respectRobots` bool, default true
- `stripLinks` bool, default false

Response:
```json
{
  "result": {
    "url": "...",
    "content": "...",
    "title": "...",
    "markdown": "...",
    "success": true,
    "partial": false,
    "source": "crawl4ai"
  },
  "timing_ms": 2345.6
}
```

### POST /map
Body fields:
- `url` string (5..2048) required — must be http/https
- `includePatterns` string[], default []
- `respectRobots` bool, default true
- `useSitemap` bool, default true

Response:
```json
{
  "urls": ["https://example.com/page1", "..."],
  "total": 42,
  "source": { "sitemap": 30, "links": 12 },
  "timing_ms": 567.8
}
```

### POST /crawl/site
Body fields:
- `url` string (5..2048) required — must be http/https
- `maxDepth` int (1..10), default 3
- `maxPages` int (1..500), default 100
- `format` enum: `markdown|text|html`, default `markdown`
- `respectRobots` bool, default true
- `includePatterns` string[], default []
- `excludePatterns` string[], default []
- `concurrency` int (1..10), default 3
- `timeoutMs` int (1000..600000), default 30000

Response:
```json
{
  "jobId": "job_xxxxx",
  "status": "running",
  "startedAt": "2026-03-14T07:50:00Z"
}
```

### GET /crawl/site/{job_id}
Query params:
- `offset` int, default 0
- `limit` int (1..100), default 50

Response:
```json
{
  "jobId": "job_xxxxx",
  "status": "completed",
  "progress": { "discovered": 50, "crawled": 45, "failed": 5 },
  "results": [
    { "url": "...", "title": "...", "content": "...", "success": true }
  ],
  "resultTotal": 45,
  "offset": 0,
  "limit": 50,
  "timing_ms": 12.3
}
```

Job status values: `running`, `completed`, `failed`, `cancelled`

### DELETE /crawl/site/{job_id}
Response:
- `200`: `{ "jobId": "...", "status": "cancelled" }`
- `404`: Job not found
- `409`: Job already completed/failed/cancelled

### Auth / Error responses
- No token => `401`
- Rate limited => `429` (60 req/min per IP)
- Max concurrent jobs => `429`
- SSRF blocked URL => `400`
- Invalid URL => `422`
- Server error => `500`

## Quick Diagnostics

```bash
# Health check
curl -i https://search.yuuzu.net/health

# Auth check (no token => 401)
curl -i https://search.yuuzu.net/search \
  -H "Content-Type: application/json" \
  -d '{"q":"test"}'

# Search with token
curl -i https://search.yuuzu.net/search \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"q":"openclaw","freshness":"week","topK":3}'

# Crawl single URL
curl -sS https://search.yuuzu.net/crawl \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","format":"markdown"}'

# Discover URLs
curl -sS https://search.yuuzu.net/map \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://docs.example.com"}'

# Start site crawl
curl -sS https://search.yuuzu.net/crawl/site \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://docs.example.com","maxPages":10,"maxDepth":2}'

# Poll site crawl status
curl -sS "https://search.yuuzu.net/crawl/site/job_xxxxx?offset=0&limit=20" \
  -H "Authorization: Bearer <TOKEN>"

# Cancel site crawl
curl -sS -X DELETE "https://search.yuuzu.net/crawl/site/job_xxxxx" \
  -H "Authorization: Bearer <TOKEN>"
```

## If Cloudflare blocks with challenge (403)
- Verify WAF/Configuration rules for `search.yuuzu.net`
- Ensure path rules include `/search`, `/health`, `/crawl`, `/map`, `/crawl/site`
- Check Security Events by Ray ID
- Confirm Security Level/BIC are not forcing challenge for API traffic

## Oracle-my container check

```bash
ssh oracle-my 'cd /data/openclaw-searxng-plus && docker compose ps'
```

> Use the SSH alias `oracle-my` configured in `~/.ssh/config`.

## Architecture Notes
- **Ranking**: Hybrid BM25 + TF-IDF + quality + freshness + language scoring (language-aware, zh-TW + en)
- **Content cleaning**: 5-stage pipeline — HTML decode, prompt injection filter, ad removal, tag strip, truncation
- **Markdown cleaning**: Link density filter, consecutive link removal, short-block analysis, boilerplate removal
- **Caching**: 6 Redis cache types — search results (1h), content (1d), domain cooldown (5m), robots.txt (1d), URL map (6h), job state (1d)
- **Security**: SSRF protection (IPv4+IPv6), robots.txt compliance, rate limiting (60/min), prompt injection defense
