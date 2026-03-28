#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <url> [format:markdown|text|html] [stripLinks:true|false]" >&2
  exit 1
fi

URL="$1"
FORMAT="${2:-markdown}"
STRIP_LINKS="${3:-false}"

TOKEN=$(grep 'GATEWAY_AUTH_TOKEN' ~/.bashrc ~/.zshrc 2>/dev/null | head -1 | sed "s/^.*GATEWAY_AUTH_TOKEN=['\"]*//" | sed "s/['\"].*$//") \
&& curl -sS https://search.yuuzu.net/crawl \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"url\":\"${URL}\",\"format\":\"${FORMAT}\",\"stripLinks\":${STRIP_LINKS}}"
