---
name: yuuzu-search
description: Use Yuuzu hosted search gateway (search.yuuzu.net / openclaw-searxng-plus) for web query tasks when the user asks to use "oracle-my websearch", "search.yuuzu.net", or this custom search API. Handles request building, token-authenticated calls to /search, /crawl, /map, and /crawl/site endpoints, parameter tuning (q, topK, freshness, needContent, needCrawl, needMap, needSiteCrawl, format, lang), and quick health/auth diagnostics.
---

# Yuuzu Search Gateway

Use this skill to query Yuuzu's custom search + crawl gateway instead of generic web search tools.

## Quick Start

Use the Bash tool with inline curl to call the gateway directly. Do NOT pre-check whether the token exists — just run the command. If it fails, show the error output to the user and stop.

**Token resolution** (inline, single line):
```bash
TOKEN=$(grep 'GATEWAY_AUTH_TOKEN' ~/.bashrc ~/.zshrc 2>/dev/null | head -1 | sed "s/^.*GATEWAY_AUTH_TOKEN=['\"]*//" | sed "s/['\"].*$//")
```

**Base URL:** `https://search.yuuzu.net`

**Default call pattern** (search example):
```bash
TOKEN=$(grep 'GATEWAY_AUTH_TOKEN' ~/.bashrc ~/.zshrc 2>/dev/null | head -1 | sed "s/^.*GATEWAY_AUTH_TOKEN=['\"]*//" | sed "s/['\"].*$//") && curl -sS https://search.yuuzu.net/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"q":"your query here","topK":5,"freshness":"any"}' | python3 -m json.tool 2>/dev/null || echo "FAILED"
```

If the curl call returns an error (401, 403, 5xx, connection refused), report the raw error to the user and stop. Do not retry or attempt token diagnostics.

## Endpoints Overview

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Health check |
| POST | `/search` | Search + optional crawl/map/site-crawl enrichment |
| POST | `/crawl` | Crawl a single URL |
| POST | `/map` | Discover URLs from a site (sitemap + link extraction) |
| POST | `/crawl/site` | Start async site crawler (returns job ID) |
| GET | `/crawl/site/{job_id}` | Poll site crawl progress + paginated results |
| DELETE | `/crawl/site/{job_id}` | Cancel a running site crawl |

## POST /search

Core search endpoint with optional enrichment flags.

**Body fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `q` | string (1..500) | required | Query string |
| `topK` | int (1..50) | 10 | Max results |
| `freshness` | `any\|day\|week\|month` | `any` | Time filter |
| `lang` | string | auto-detect | Force language (`en`, `zh-TW`) |
| `needContent` | bool | false | Fetch page body via lightweight fetcher |
| `needCrawl` | bool | false | Deep crawl via Crawl4AI (richer than needContent) |
| `needMap` | bool | false | Discover related URLs per result domain |
| `needSiteCrawl` | bool | false | Launch async site crawl per result domain |
| `format` | `markdown\|text\|html` | `markdown` | Output format (when needCrawl/needSiteCrawl) |
| `stripLinks` | bool | false | Remove markdown links from content |
| `crawlMaxDepth` | int (1..5) | 1 | Crawl depth |
| `crawlMaxPages` | int (1..20) | 1 | Crawl page limit |
| `crawlTimeoutMs` | int (1000..120000) | 15000 | Crawl timeout |
| `crawlConcurrency` | int (1..10) | 3 | Parallel crawl workers |
| `crawlOnlyMainContent` | bool | true | Extract main content only |
| `crawlBypassCache` | bool | false | Skip cached content |
| `crawlRespectRobots` | bool | true | Respect robots.txt |
| `siteCrawlMaxDepth` | int (1..10) | 1 | Site crawl depth |
| `siteCrawlMaxPages` | int (1..500) | 5 | Site crawl page limit |
| `siteCrawlConcurrency` | int (1..10) | 3 | Site crawl workers |
| `siteCrawlIncludePatterns` | string[] | [] | URL include globs |
| `siteCrawlExcludePatterns` | string[] | [] | URL exclude globs |

**Response fields per result:**

| Field | Type | Description |
|-------|------|-------------|
| `title` | string | Page title |
| `url` | string | Page URL |
| `snippet` | string | Sanitized snippet |
| `content` | string? | Full page content (when needContent/needCrawl) |
| `score` | float | Hybrid ranking score |
| `source` | string | Search engine source |
| `content_partial` | bool | Whether content was truncated |
| `relatedUrls` | string[]? | Discovered URLs (when needMap) |
| `siteCrawlJobId` | string? | Async job ID (when needSiteCrawl) |

**Example — basic search:**
```bash
TOKEN=$(grep 'GATEWAY_AUTH_TOKEN' ~/.bashrc ~/.zshrc 2>/dev/null | head -1 | sed "s/^.*GATEWAY_AUTH_TOKEN=['\"]*//" | sed "s/['\"].*$//") && curl -sS https://search.yuuzu.net/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"q":"OpenClaw ACP runtime","topK":5,"freshness":"week"}'
```

**Example — with crawl enrichment:**
```bash
TOKEN=$(grep 'GATEWAY_AUTH_TOKEN' ~/.bashrc ~/.zshrc 2>/dev/null | head -1 | sed "s/^.*GATEWAY_AUTH_TOKEN=['\"]*//" | sed "s/['\"].*$//") && curl -sS https://search.yuuzu.net/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"q":"FastAPI best practices","topK":5,"needCrawl":true,"format":"markdown"}'
```

## POST /crawl

Crawl a single URL and return cleaned content.

**Body:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `url` | string | required | HTTP/HTTPS URL |
| `maxDepth` | int (1..5) | 1 | Crawl depth |
| `maxPages` | int (1..20) | 1 | Page limit |
| `timeoutMs` | int (1000..120000) | 15000 | Timeout |
| `onlyMainContent` | bool | true | Main content extraction |
| `bypassCache` | bool | false | Skip cache |
| `format` | `markdown\|text\|html` | `markdown` | Output format |
| `respectRobots` | bool | true | Respect robots.txt |
| `stripLinks` | bool | false | Remove links |

**Response:** `{ result: { url, content, title, markdown, success, partial, source }, timing_ms }`

```bash
TOKEN=$(grep 'GATEWAY_AUTH_TOKEN' ~/.bashrc ~/.zshrc 2>/dev/null | head -1 | sed "s/^.*GATEWAY_AUTH_TOKEN=['\"]*//" | sed "s/['\"].*$//") && curl -sS https://search.yuuzu.net/crawl \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/article","format":"markdown"}'
```

## POST /map

Discover URLs from a website via sitemap.xml + HTML link extraction.

**Body:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `url` | string | required | Target site URL |
| `includePatterns` | string[] | [] | URL glob filters |
| `respectRobots` | bool | true | Filter by robots.txt |
| `useSitemap` | bool | true | Try sitemap.xml |

**Response:** `{ urls: string[], total: int, source: { sitemap: int, links: int }, timing_ms }`

```bash
TOKEN=$(grep 'GATEWAY_AUTH_TOKEN' ~/.bashrc ~/.zshrc 2>/dev/null | head -1 | sed "s/^.*GATEWAY_AUTH_TOKEN=['\"]*//" | sed "s/['\"].*$//") && curl -sS https://search.yuuzu.net/map \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://docs.example.com","includePatterns":["*/api/*"]}'
```

## POST /crawl/site (Async)

Start a background site crawl job. Returns immediately with a job ID.

**Body:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `url` | string | required | Start URL |
| `maxDepth` | int (1..10) | 3 | BFS depth |
| `maxPages` | int (1..500) | 100 | Page limit |
| `format` | `markdown\|text\|html` | `markdown` | Output format |
| `respectRobots` | bool | true | Respect robots.txt |
| `includePatterns` | string[] | [] | URL include globs |
| `excludePatterns` | string[] | [] | URL exclude globs |
| `concurrency` | int (1..10) | 3 | Parallel workers |
| `timeoutMs` | int (1000..600000) | 30000 | Overall timeout |

**Response:** `{ jobId, status, startedAt }`

**Poll progress:** `GET /crawl/site/{jobId}?offset=0&limit=50`
- Returns `{ jobId, status, progress: { discovered, crawled, failed }, results: [...], resultTotal, offset, limit, timing_ms }`
- Status: `running` | `completed` | `failed` | `cancelled`

**Cancel:** `DELETE /crawl/site/{jobId}`
- Returns `{ jobId, status: "cancelled" }` or `409` if already finished.

## Parameter Guidance

- `freshness=week` for fast-moving topics; `freshness=any` for broad research.
- `topK` between 3-10 for agent workflows.
- `needContent=true` for lightweight body text (fast, cached).
- `needCrawl=true` for deep content extraction with Readability + Markdown cleaning (slower, higher quality).
- `needMap=true` to discover sibling pages on result domains.
- `needSiteCrawl=true` to launch background crawl jobs per domain (check `siteCrawlJobId` in results to poll).
- `format=markdown` (default) for LLM consumption; `format=text` for plain text; `format=html` for raw HTML.
- `lang=zh-TW` to force Traditional Chinese ranking boost; omit for auto-detection.
- `stripLinks=true` when downstream doesn't need hyperlinks in content.

## Troubleshooting

1. `403` with Cloudflare challenge => check Cloudflare WAF rules for `search.yuuzu.net`.
2. `401` => token is missing/invalid.
3. `429` => rate limit (60 req/min) or max concurrent site crawl jobs reached.
4. `5xx` => verify gateway/searxng/redis containers on oracle-my.

For detailed ops checklist: `references/runbook.md`

## Error Handling

If the curl call fails, show the raw output to the user and stop. Common errors:
- `401` — token missing or invalid
- `403` — Cloudflare WAF block
- `429` — rate limit (60 req/min)
- `5xx` — gateway/backend down

Do NOT attempt to diagnose or fix token issues. Just report the error.

## Resources

### scripts/
- `scripts/search_request.sh` — Search query helper (fallback, prefer inline curl)
- `scripts/crawl_request.sh` — Single URL crawl helper (fallback)
- `scripts/map_request.sh` — URL discovery helper (fallback)

### references/
- `references/runbook.md` — Full API contract, deployment, diagnostics, and Cloudflare notes
