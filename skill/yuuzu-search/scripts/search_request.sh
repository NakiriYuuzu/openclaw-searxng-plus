#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <query> [freshness:any|day|week|month] [topK:1-50] [needContent:true|false]" >&2
  exit 1
fi

QUERY="$1"
FRESHNESS="${2:-week}"
TOPK="${3:-5}"
NEED_CONTENT="${4:-false}"

TOKEN=$(grep 'GATEWAY_AUTH_TOKEN' ~/.bashrc ~/.zshrc 2>/dev/null | head -1 | sed "s/^.*GATEWAY_AUTH_TOKEN=['\"]*//" | sed "s/['\"].*$//") \
&& curl -sS https://search.yuuzu.net/search \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"q\":\"${QUERY}\",\"freshness\":\"${FRESHNESS}\",\"topK\":${TOPK},\"needContent\":${NEED_CONTENT}}"
