#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <url> [includePattern]" >&2
  exit 1
fi

URL="$1"
INCLUDE_PATTERN="${2:-}"

TOKEN=$(grep 'GATEWAY_AUTH_TOKEN' ~/.bashrc ~/.zshrc 2>/dev/null | head -1 | sed "s/^.*GATEWAY_AUTH_TOKEN=['\"]*//" | sed "s/['\"].*$//")

if [[ -n "$INCLUDE_PATTERN" ]]; then
  curl -sS https://search.yuuzu.net/map \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"url\":\"${URL}\",\"includePatterns\":[\"${INCLUDE_PATTERN}\"]}"
else
  curl -sS https://search.yuuzu.net/map \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"url\":\"${URL}\"}"
fi
