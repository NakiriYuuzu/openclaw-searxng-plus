#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${YUUZU_SEARCH_BASE_URL:-}"
TOKEN="${GATEWAY_AUTH_TOKEN:-}"

usage() {
  cat >&2 <<'EOF'
Usage:
  search_request.sh search <query> [freshness:any|day|week|month] [topK:1-50] [needContent:true|false] [needCrawl:true|false]
  search_request.sh crawl <url> [maxDepth] [maxPages] [timeoutMs] [onlyMainContent:true|false]

Env:
  GATEWAY_AUTH_TOKEN    Required. Bearer token for your gateway
  YUUZU_SEARCH_BASE_URL Required. Base URL for your search gateway
EOF
  exit 1
}

require_token() {
  if [[ -z "$TOKEN" ]]; then
    echo "Missing GATEWAY_AUTH_TOKEN in environment. Put it in ~/.bashrc (Linux) or ~/.zshrc (macOS), then reload your shell." >&2
    exit 1
  fi
  if [[ -z "$BASE_URL" ]]; then
    echo "Missing YUUZU_SEARCH_BASE_URL in environment. Set your private gateway base URL in ~/.bashrc or ~/.zshrc, then reload your shell." >&2
    exit 1
  fi
}

mode="${1:-}"
[[ -n "$mode" ]] || usage
shift || true

case "$mode" in
  search)
    [[ $# -ge 1 ]] || usage
    require_token
    QUERY="$1"
    FRESHNESS="${2:-week}"
    TOPK="${3:-5}"
    NEED_CONTENT="${4:-false}"
    NEED_CRAWL="${5:-false}"

    curl -sS "${BASE_URL}/search" \
      -H "Authorization: Bearer ${TOKEN}" \
      -H "Content-Type: application/json" \
      -d "{\"q\":\"${QUERY}\",\"freshness\":\"${FRESHNESS}\",\"topK\":${TOPK},\"needContent\":${NEED_CONTENT},\"needCrawl\":${NEED_CRAWL}}"
    ;;
  crawl)
    [[ $# -ge 1 ]] || usage
    require_token
    URL="$1"
    MAX_DEPTH="${2:-1}"
    MAX_PAGES="${3:-1}"
    TIMEOUT_MS="${4:-12000}"
    ONLY_MAIN="${5:-true}"

    curl -sS "${BASE_URL}/crawl" \
      -H "Authorization: Bearer ${TOKEN}" \
      -H "Content-Type: application/json" \
      -d "{\"url\":\"${URL}\",\"maxDepth\":${MAX_DEPTH},\"maxPages\":${MAX_PAGES},\"timeoutMs\":${TIMEOUT_MS},\"onlyMainContent\":${ONLY_MAIN}}"
    ;;
  *)
    usage
    ;;
esac
