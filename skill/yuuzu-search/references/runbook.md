# Runbook: your-search-gateway.example.com

## Topology
- Public endpoint: `https://your-search-gateway.example.com`
- Backend: oracle-my `openclaw-searxng-plus`
- Auth: `Authorization: Bearer <GATEWAY_AUTH_TOKEN>`

## API Contract

### POST /search
Body fields:
- `q` string (1..500) required
- `topK` int (1..50), default 10
- `needContent` bool, default false
- `freshness` enum: `any|day|week|month`, default `any`

### Health/Auth checks
- `/health` => 200
- `/search` without token => 401
- `/search` with token => 200

## Quick Diagnostics

```bash
curl -i https://your-search-gateway.example.com/health
curl -i https://your-search-gateway.example.com/search \
  -H "Content-Type: application/json" \
  -d '{"q":"openclaw","freshness":"week","topK":3,"needContent":false}'
curl -i https://your-search-gateway.example.com/search \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"q":"openclaw","freshness":"week","topK":3,"needContent":false}'
```

## If Cloudflare blocks with challenge (403)
- Verify WAF/Configuration rules for `your-search-gateway.example.com`
- Ensure path rules include `/search` and `/health`
- Check Security Events by Ray ID
- Confirm Security Level/BIC are not forcing challenge for API traffic

## Oracle-my container check

```bash
ssh -i ~/.ssh/oracle-malaysia.key ubuntu@149.118.151.163 \
  'cd /data/openclaw-searxng-plus && docker compose ps'
```
