# openclaw-searxng-plus: Search + Crawl Platform Design

> 一站式搜尋 + 抓取 + URL 發現平台，目標對標 Brave Search API + Firecrawl + Cloudflare Crawl

## 目標

將現有的 SearXNG 搜尋閘道擴展為完整的搜尋 + 爬取平台，提供：

- **Web 搜尋** — 現有 SearXNG 元搜尋 + 混合重排序（已有）
- **單頁抓取** — 透過 Crawl4AI 提取乾淨內容（已有，強化輸出格式）
- **全站爬取** — 非同步全站深度爬取，任務管理
- **URL 發現** — sitemap + 頁面連結提取
- **搜尋整合** — `/search` 端點串接以上所有能力

## 設計決策

| 項目 | 決策 | 理由 |
|------|------|------|
| 爬取架構 | 強化 Crawl4AI 整合 | 複用現有基礎設施，gateway 層管理上層邏輯 |
| 結構化擷取 | 暫不實作 | 先聚焦搜尋 + 爬取核心能力 |
| 非同步任務 | Redis 狀態 + asyncio 執行 | 不增加新服務，簡單務實 |
| 輸出格式 | Markdown + 純文字 + 原始 HTML | 涵蓋主要 AI 使用場景 |
| robots.txt | 預設尊重，可關閉 | 負責任的爬取禮儀 |
| URL 發現 | 基本版（連結 + sitemap） | 滿足需求，避免過度工程 |
| API 風格 | 自定義，延續現有扁平欄位風格 | 一致性，向後相容 |
| 實作方案 | 漸進擴展（方案 A） | 早期階段，最小改動，向後相容 |

## 破壞性變更與遷移

本設計 **不包含** 破壞性變更。所有新欄位均為 optional，現有 API 行為完全保留：

- `/search` 新增的 `format`、`needMap`、`needSiteCrawl` 等欄位皆有預設值
- `/crawl` 新增的 `format`、`respectRobots` 皆有預設值
- 現有 `content_partial` 欄位保留不動

## API 端點

### 現有端點（強化）

#### `POST /search`

搜尋 + 可選內容抓取 + URL 發現 + 全站爬取。

**Request:**

延續現有扁平欄位風格（與現有 `SearchRequest` 一致）。

```json
{
  "q": "搜尋查詢",
  "topK": 10,
  "freshness": "any | day | week | month",
  "lang": "en | zh-TW",
  "format": "markdown",

  "needCrawl": false,
  "needContent": false,
  "needMap": false,
  "needSiteCrawl": false,

  "crawlMaxDepth": 1,
  "crawlMaxPages": 1,
  "crawlTimeoutMs": 15000,
  "crawlConcurrency": 3,
  "crawlOnlyMainContent": true,
  "crawlBypassCache": false,
  "crawlRespectRobots": true,

  "siteCrawlMaxDepth": 1,
  "siteCrawlMaxPages": 5,
  "siteCrawlConcurrency": 3,
  "siteCrawlIncludePatterns": [],
  "siteCrawlExcludePatterns": []
}
```

新增欄位說明：
- `format`（預設 `"markdown"`）：僅在 `needCrawl` 或 `needSiteCrawl` 為 true 時生效，控制內容輸出格式
- `needMap`（預設 `false`）：對 topK 結果的每個網域執行 URL 發現
- `needSiteCrawl`（預設 `false`）：對 topK 結果觸發全站非同步爬取
- `crawlRespectRobots`（預設 `true`）：爬取前檢查 robots.txt
- `siteCrawl*` 系列：全站爬取參數，僅在 `needSiteCrawl` 為 true 時生效

**Response:**

```json
{
  "results": [
    {
      "title": "標題",
      "url": "https://example.com/page",
      "snippet": "摘要",
      "score": 0.85,
      "source": "google",
      "content": "完整 Markdown 內容（needCrawl 時，可選）",
      "content_partial": false,
      "relatedUrls": ["..."],
      "siteCrawlJobId": "job_abc123"
    }
  ],
  "timing_ms": 342.5,
  "query": "搜尋查詢",
  "total_found": 47
}
```

回應欄位說明：
- `content`（Optional）：僅在 `needCrawl: true` 時填入
- `content_partial`（現有欄位，保留）：內容是否為部分擷取
- `relatedUrls`（Optional）：僅在 `needMap: true` 時填入
- `siteCrawlJobId`（Optional）：僅在 `needSiteCrawl: true` 時填入
- `total_found`：始終為 SearXNG 搜尋結果數量，不含 map 發現的 URL

**整合模式：**

- `needCrawl: true` — 對 topK 結果逐頁抓取內容（同步）
- `needMap: true` — 對 topK 結果的每個網域執行 URL 發現（同步）
- `needSiteCrawl: true` — 對 topK 結果觸發全站非同步爬取（回傳 jobId）
- 三個 flag 可任意組合，彼此不互斥

**快取鍵：** 包含 `q`、`topK`、`freshness`、`lang`、`needCrawl`、`needMap`、`needSiteCrawl`、`format` 在內。`needSiteCrawl` 的結果中 `siteCrawlJobId` 不被快取——快取命中時若帶有 `needSiteCrawl: true`，會建立新任務並替換 jobId 後回傳。

**執行流程：**

```
POST /search
    → 快取檢查（key 包含所有 flag）
    → SearXNG 查詢
    → 標準化 → 去重 → 重排序 → 清理
    → 根據 flags 平行執行：
        ├─ needCrawl     → crawl_client 逐頁抓取（同步）
        ├─ needMap       → map_client 發現 URL（同步）
        └─ needSiteCrawl → job_manager 建立任務（非同步，回傳 jobId）
    → 組裝回應 → 快取儲存（排除 siteCrawlJobId） → 回傳
```

#### `POST /crawl`

單頁抓取（強化輸出格式）。

**完整 Request（現有 + 新增欄位）：**

```json
{
  "url": "https://example.com",
  "maxDepth": 1,
  "maxPages": 1,
  "timeoutMs": 15000,
  "onlyMainContent": true,
  "bypassCache": false,
  "format": "markdown",
  "respectRobots": true
}
```

新增欄位：
- `format`（預設 `"markdown"`）：`markdown | text | html`
- `respectRobots`（預設 `true`）：爬取前檢查 robots.txt

### 新增端點

> 以下模組皆為新建檔案（to-be-created）。

#### `POST /crawl/site`

全站非同步爬取。

**Request:**

```json
{
  "url": "https://example.com",
  "maxDepth": 2,
  "maxPages": 50,
  "format": "markdown",
  "respectRobots": true,
  "includePatterns": ["https://example.com/blog/*"],
  "excludePatterns": ["*/login", "*/admin/*"],
  "concurrency": 3,
  "timeoutMs": 30000
}
```

驗證規則：
- `maxPages`：預設 100，硬上限 500（validator 拒絕 >500）
- `maxDepth`：預設 3，硬上限 10
- `concurrency`：預設 3，硬上限 10

**Response:**

```json
{
  "jobId": "job_abc123",
  "status": "running",
  "startedAt": "2026-03-14T12:00:00Z"
}
```

#### `GET /crawl/site/{job_id}`

查詢爬取狀態與結果。

**Query Parameters:**
- `offset`（預設 `0`）：結果分頁偏移
- `limit`（預設 `50`，上限 `100`）：每頁結果數

**Response:**

```json
{
  "jobId": "job_abc123",
  "status": "running | completed | failed | cancelled",
  "progress": {
    "discovered": 120,
    "crawled": 45,
    "failed": 2
  },
  "results": [
    {
      "url": "https://example.com/page",
      "title": "頁面標題",
      "content": "Markdown 內容",
      "success": true
    }
  ],
  "resultTotal": 45,
  "offset": 0,
  "limit": 50,
  "timing_ms": 15234
}
```

#### `DELETE /crawl/site/{job_id}`

取消進行中的爬取任務。

**Response (200):**
```json
{
  "jobId": "job_abc123",
  "status": "cancelled"
}
```

**Error Cases:**
- 任務不存在：`404 {"detail": "Job not found"}`
- 任務已完成/已取消：`409 {"detail": "Job already completed", "status": "completed"}`

#### `POST /map`

URL 發現。

**Request:**

```json
{
  "url": "https://example.com",
  "includePatterns": ["*/blog/*"],
  "respectRobots": true,
  "useSitemap": true
}
```

**Response:**

```json
{
  "urls": ["https://example.com/blog/post-1", "..."],
  "total": 87,
  "source": { "sitemap": 60, "links": 27 },
  "timing_ms": 1234
}
```

#### `GET /health`

維持不變。

## 核心模組架構

### 新增模組（to-be-created）

#### `gateway/robots.py` — robots.txt 檢查器

- 解析目標網域的 `robots.txt`
- 快取解析結果到 Redis（TTL 24 小時）
- 提供 `is_allowed(url, user_agent)` 方法
- 使用 Python 內建 `urllib.robotparser`
- 容錯：抓取失敗或解析錯誤 → 視為允許（寬鬆策略）

#### `gateway/site_crawler.py` — 全站爬取引擎

- URL 佇列管理（BFS，按深度層級）
- 每一頁透過現有 `crawl_client.py` 呼叫 Crawl4AI
- 從回傳 HTML 中提取新 URL（`<a href>`），加入佇列
- `includePatterns` / `excludePatterns` 過濾（fnmatch glob）
- `asyncio.Semaphore` 控制並發
- 爬取前檢查 `robots.py`
- 進度即時更新到 Redis
- 單頁失敗不中斷任務，記錄到 `progress.failed`
- 同一網域連續失敗 3 次觸發冷卻

#### `gateway/job_manager.py` — 非同步任務管理

- 任務生命週期：`pending → running → completed | failed | cancelled`
- 任務狀態存 Redis（hash key: `job:{job_id}`）
- 啟動：建立 `asyncio.Task`，註冊到記憶體 dict
- 取消：`task.cancel()` + 更新 Redis 狀態
- 啟動時恢復：讀取 Redis 中 `running` 狀態的任務，標記為 `failed`（reason: `"server restarted"`），不重新排程。原因是 BFS 狀態（visited set、URL queue）僅存在於記憶體，無法安全恢復
- 結果存 Redis（TTL 可配，預設 24 小時）
- 同時任務數上限（預設 10）

#### `gateway/map_client.py` — URL 發現

- 抓取 `sitemap.xml`（支援 sitemap index 遞迴）
- 抓取首頁 HTML，提取 `<a>` 連結
- URL 去重 + 過濾（同網域、pattern matching）
- 合併兩個來源，標記來源
- `map_timeout`：整個 `/map` 操作的 wall-clock 逾時（含 sitemap 抓取 + 頁面連結提取），預設 10 秒

### 現有模組修改

#### `gateway/models.py`

新增 model：
- `SiteCrawlRequest` — 全站爬取請求
- `SiteCrawlJobResponse` — 全站爬取建立回應（jobId + status）
- `SiteCrawlStatusResponse` — 任務狀態查詢回應（含分頁）
- `JobCancelResponse` — 任務取消回應
- `MapRequest` — URL 發現請求
- `MapResponse` — URL 發現回應
- `OutputFormat` Enum — `markdown | text | html`

修改 model：
- `SearchRequest`：新增 `format`（預設 `"markdown"`）、`needMap`（預設 `false`）、`needSiteCrawl`（預設 `false`）、`crawlRespectRobots`（預設 `true`）、`siteCrawlMaxDepth`、`siteCrawlMaxPages`、`siteCrawlConcurrency`、`siteCrawlIncludePatterns`、`siteCrawlExcludePatterns`
- `SearchResult`：新增 `relatedUrls`（Optional）、`siteCrawlJobId`（Optional），保留現有 `content_partial`
- `CrawlRequest`：新增 `format`（預設 `"markdown"`）、`respectRobots`（預設 `true`）
- `CrawlOptions`：新增 `respectRobots`（預設 `true`）

#### `gateway/app.py`

- 新增路由：`POST /crawl/site`、`GET /crawl/site/{job_id}`、`DELETE /crawl/site/{job_id}`、`POST /map`
- 啟動事件中初始化 `JobManager`，將 Redis 中 `running` 狀態的任務標記為 `failed`
- `/search` 路由整合 `needMap` 和 `needSiteCrawl` 邏輯

#### `gateway/crawl_client.py`

- 新增 `format` 參數處理（markdown / text / html 選擇回傳內容）
- 新增 `respectRobots` 檢查（呼叫 `robots.py`）

#### `gateway/cache.py`

- 新增任務狀態相關的 Redis 操作方法（get/set job state, progress, results）
- 新增 robots.txt 快取方法
- 新增 map 結果快取方法

## 資料流

### 全站爬取流程

```
POST /crawl/site
    → job_manager 建立任務 + 存 Redis
    → asyncio.Task 啟動 site_crawler
        → map_client 發現初始 URL（sitemap + 首頁連結）
        → robots.py 過濾不允許的 URL
        → includePatterns / excludePatterns 過濾
        → BFS 逐層：
            → crawl_client → Crawl4AI（受 Semaphore 控制）
            → 提取新 URL → 過濾 → 加入佇列
            → 結果累積存 Redis
            → 進度即時更新
        → 任務完成 → 更新 Redis 狀態
    → 回傳 jobId

GET /crawl/site/{job_id}?offset=0&limit=50
    → job_manager 從 Redis 讀取狀態 + 分頁結果
```

### `/search` 整合流程

```
POST /search (needCrawl + needMap + needSiteCrawl)
    → 快取檢查（key 包含所有 flag）
    → SearXNG 查詢（第 1-2 頁）
    → 標準化 → 去重 → 重排序 → 清理
    → 平行執行：
        ├─ needCrawl     → crawl_client 逐頁抓取
        ├─ needMap       → map_client URL 發現
        └─ needSiteCrawl → job_manager 建立非同步任務
    → 組裝回應（content, relatedUrls, siteCrawlJobId）
    → 快取儲存（排除 siteCrawlJobId） → 回傳
```

## 快取策略

| 資源 | Redis Key 模式 | TTL |
|------|----------------|-----|
| 搜尋結果 | `search:{hash}` | 1 小時（現有） |
| 單頁內容 | `content:{url_hash}` | 24 小時（現有） |
| robots.txt | `robots:{domain}` | 24 小時（新增） |
| Map 結果 | `map:{domain_hash}` | 6 小時（新增） |
| 爬取任務狀態 | `job:{job_id}` | 24 小時（新增） |
| 爬取任務結果 | `job:{job_id}:results` | 24 小時（新增） |
| 網域冷卻 | `cooldown:{domain}` | 5 分鐘（現有） |

- 全站爬取的個別頁面也寫入 `content:{url_hash}`，後續 `/crawl` 或 `/search` + `needCrawl` 可命中快取
- 搜尋快取 key 包含 `needCrawl`、`needMap`、`needSiteCrawl`、`format` 等 flag
- `siteCrawlJobId` 不納入快取，快取命中時若需要 siteCrawl 會建立新任務

## 錯誤處理

### 全站爬取

- 單頁失敗不中斷任務，記錄到 `progress.failed`
- 任務級別逾時上限（預設 300 秒，可配）
- 同一網域連續失敗 3 次觸發冷卻（複用現有 domain cooldown）
- Crawl4AI 服務不可用 → 任務標記 `failed`，回傳錯誤原因
- 服務重啟 → 進行中的任務標記為 `failed`（reason: `"server restarted"`）

### robots.txt

- 抓取失敗（超時、404）→ 視為允許（寬鬆策略）
- 解析錯誤 → 記 log，視為允許

### `/map`

- sitemap.xml 不存在 → 只從頁面連結提取
- 頁面抓取失敗 → 回傳空列表 + 錯誤訊息

## 設定（`config.py` 新增）

```python
# 全站爬取
site_crawl_max_depth: int = 3          # 預設深度，硬上限 10
site_crawl_max_pages: int = 100        # 預設頁數，硬上限 500
site_crawl_timeout: int = 300          # 任務總逾時（秒）
site_crawl_concurrency: int = 3
site_crawl_domain_fail_limit: int = 3

# Map
map_timeout: float = 10.0              # 整個 /map 操作的 wall-clock 逾時

# robots.txt
robots_cache_ttl: int = 86400
respect_robots_default: bool = True

# 任務管理
job_result_ttl: int = 86400
job_max_concurrent: int = 10           # 同時進行的全站爬取任務上限
```

## 安全性

- 所有新端點複用現有 Bearer Token 認證 + 速率限制
- `/crawl/site` 的 `maxPages` 硬上限 500（validator 拒絕超過），防止資源濫用
- `/crawl/site` 獨立並發限制：每個 token 同時最多 `job_max_concurrent`（預設 10）個全站爬取任務
- `includePatterns` 限制為同網域，防止跨網域擴散
- SSRF 檢查套用到 sitemap 解析和連結提取中發現的每個 URL
- 任務並發數上限防止資源耗盡

## 測試策略

### 新增測試檔案

**`tests/test_robots.py`**
- robots.txt 解析正確性（允許/禁止）
- 不存在 → 預設允許
- Redis 快取命中/未命中
- 解析錯誤容錯

**`tests/test_site_crawler.py`**
- BFS 深度控制
- maxPages 上限截止
- includePatterns / excludePatterns 過濾
- 並發控制
- 單頁失敗不中斷
- 網域連續失敗觸發冷卻

**`tests/test_job_manager.py`**
- 任務建立 / 查詢 / 取消生命週期
- Redis 狀態持久化
- 同時任務數上限
- 任務逾時處理
- 重啟後任務標記 failed

**`tests/test_map.py`**
- sitemap.xml 解析（含 sitemap index 遞迴）
- 頁面連結提取
- URL 去重與同網域過濾
- sitemap 不存在 fallback
- wall-clock 逾時

**`tests/test_api.py`（擴充）**
- 新端點認證、基本流程
- `/crawl/site` 建立 / 查詢 / 取消（含 404、409）
- `/search` 的 `needMap`、`needSiteCrawl` 整合
- 快取鍵正確包含新 flag

### 測試方式

- 延續現有：`pytest` + `pytest-asyncio` + `pytest-httpx` + `fakeredis`
- Crawl4AI 呼叫用 `pytest-httpx` mock
- 不需要真實網路請求
