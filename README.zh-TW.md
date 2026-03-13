# openclaw-searxng-plus

這是一個給 OpenClaw 使用的自架搜尋與爬取 gateway。

它整合了：
- **SearXNG**：提供 metasearch
- **FastAPI gateway**：負責驗證、排序、快取與協調
- **Crawl4AI**：提供 `/crawl` 與 `/search` 的 `needCrawl` 強化
- **Redis**：快取與冷卻狀態

目前部署版本支援：
- `POST /search`
- `POST /crawl`

實際對外 base URL 建議放在環境變數，不要直接寫死在共享文件裡。

## 這個 repo 在做什麼

這個專案不是單純包一層 SearXNG，而是把搜尋結果整理成更適合 agent workflow 的形式：
- 單一 Bearer token 驗證模型
- 結果標準化與去重
- 重排序
- 可選的內容抓取
- 可選的 Crawl4AI 自動 crawl 強化
- 可部署在 Cloudflare tunnel 後方

## 功能重點

- **`/search`** 支援：
  - `q`, `topK`, `freshness`, `needContent`
  - `needCrawl=true`：對搜尋結果前幾筆自動進一步 crawl
- **`/crawl`**：直接對指定 URL 做抽取
- **搜尋 / crawl 共用同一組 token**
- **Redis 快取**
- **內部服務架構**：
  - gateway
  - searxng
  - redis
  - crawl4ai
- **適合 Cloudflare 的部署 compose**

## API 概覽

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

## 本機開發

### 需求
- Python 3.12+
- Docker + Docker Compose
- 建議使用 `uv`

### 設定
先把 `.env.example` 複製成 `.env`，至少要設定：

```bash
GATEWAY_AUTH_TOKEN=your-secure-token
```

### 測試

```bash
.venv/bin/pytest -q
```

### 本機啟動

```bash
docker compose up -d --build
```

本機服務位置：
- gateway: `127.0.0.1:8000`
- searxng: `127.0.0.1:8888`
- crawl4ai: `127.0.0.1:11235`

## 正式部署

這個 repo 目前有兩份 compose：

- `docker-compose.yml`
  - 適合本機 / 開發
  - gateway 會綁 host `8000`
- `docker-compose.deploy.yml`
  - 適合正式環境
  - 適用已經有 `cloudflare_default` network 的主機
  - gateway 不直接對 host 開 port，避免跟既有服務衝突

如果是 tunnel / Cloudflare network 架構，建議用：

```bash
docker compose -f docker-compose.deploy.yml up -d --build
```

## Skill 同步

這個 repo 也同步收錄了 `yuuzu-search` skill：

- `skill/yuuzu-search/SKILL.md`
- `skill/yuuzu-search/scripts/search_request.sh`
- `skill/yuuzu-search/references/runbook.md`

helper script 會預設從 shell 環境變數讀取：
- `GATEWAY_AUTH_TOKEN`
- `YUUZU_SEARCH_BASE_URL`

## curl 範例

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

## 文件

- 設計文件：`docs/DESIGN.md`
- 維運筆記：`skill/yuuzu-search/references/runbook.md`

## 授權

請參考 repo 內授權與各上游依賴授權。
