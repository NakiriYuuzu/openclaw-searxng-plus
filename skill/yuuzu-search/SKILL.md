---
name: yuuzu-search
description: Use Yuuzu hosted search gateway whenever the user asks for "oracle-my websearch", a private custom search API, `/yuuzu_search`, or wants to use Yuuzu's own search/crawl gateway instead of generic web search. Handles token-authenticated `/search` and `/crawl` calls, auto-reads `GATEWAY_AUTH_TOKEN` from the shell environment by default, supports `needContent` and `needCrawl`, and includes quick auth/health diagnostics.
---

# Yuuzu Search Gateway

Use this skill to query Yuuzu's hosted search gateway instead of generic web search tools.

## Default auth behavior

Prefer this auth order:

1. `GATEWAY_AUTH_TOKEN` from the current shell environment
2. If missing, tell the user to export it in shell startup files:
   - Linux: `~/.bashrc`
   - macOS zsh: `~/.zshrc`
3. Do not hardcode the token inside the request body or the skill text sent back to the user.

Also prefer this base URL env when available:

- `YUUZU_SEARCH_BASE_URL` (set this explicitly in your shell environment)

## Quick Start

### Search endpoint

- Endpoint: `$YUUZU_SEARCH_BASE_URL/search`
- Header: `Authorization: Bearer $GATEWAY_AUTH_TOKEN`

Body fields:
- `q` (required)
- `topK` (1-50, default 10)
- `freshness` (`any|day|week|month`)
- `needContent` (`true|false`)
- `needCrawl` (`true|false`, optional)
- `crawlMaxDepth`, `crawlMaxPages`, `crawlTimeoutMs`, `crawlOnlyMainContent`, `crawlBypassCache` (optional when `needCrawl=true`)

Example:

```bash
export YUUZU_SEARCH_BASE_URL="https://your-search-gateway.example.com"

curl -sS "$YUUZU_SEARCH_BASE_URL/search" \
  -H "Authorization: Bearer $GATEWAY_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"q":"OpenClaw ACP runtime","freshness":"week","topK":5,"needContent":false,"needCrawl":false}'
```

### Crawl endpoint

- Endpoint: `$YUUZU_SEARCH_BASE_URL/crawl`

Example:

```bash
curl -sS "$YUUZU_SEARCH_BASE_URL/crawl" \
  -H "Authorization: Bearer $GATEWAY_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://docs.openclaw.ai","maxDepth":1,"maxPages":1,"timeoutMs":12000,"onlyMainContent":true}'
```

## Response Expectations

- `GET /health` => `200` and `{"status":"ok"}`
- `POST /search` without token => `401`
- `POST /search` with valid token => `200` and `results[]`
- `POST /crawl` with valid token => `200` and `result`

## Parameter Guidance

- Use `freshness=week` for fast-moving topics.
- Use `freshness=any` for broad research.
- Keep `topK` between 3 and 10 for agent workflows.
- Set `needContent=true` only when downstream steps need page body text.
- Set `needCrawl=true` when search results should be auto-enriched with crawl output.
- Use `/crawl` directly when the user already knows the target URL.

## Troubleshooting

1. If response is `401`, the shell likely does not have the right `GATEWAY_AUTH_TOKEN`.
2. If response is `403` with Cloudflare challenge, check Cloudflare rules (WAF/Under Attack/BIC).
3. If response is `5xx`, verify gateway/searxng/redis/crawl4ai on oracle-my.
4. If `/search` works but `/crawl` fails, verify Crawl4AI service health and deployment compose.

For detailed ops checklist, read:
- `references/runbook.md`

## Resources

### scripts/
- `scripts/search_request.sh`: env-first query helper for `/search` and `/crawl`.

### references/
- `references/runbook.md`: deployment, diagnostics, and Cloudflare notes.
