# Content Extraction Quality Upgrade — Design Spec

**Goal:** Upgrade content cleaning to Firecrawl/Brave Search quality level. Remove navigation, headers, footers, sidebars, and ads from crawled content, keeping only main article content.

**Approach:** Dual-layer extraction — HTML-level readability extraction + markdown post-processing.

---

## Problem

Crawl4AI's `onlyMainContent` returns content where 66–88% is navigation links, menus, footers, and boilerplate. The current `sanitizer.py` only handles prompt injection and ad text patterns — it has no structural content cleaning.

## Architecture

### Data Flow

```
Crawl4AI response
  → _extract_content() extracts html + markdown
  → Layer 1: readability-lxml extracts main content from HTML → html_to_markdown()
  → Layer 2: clean_markdown() removes residual noise from markdown
  → Existing sanitize_content() handles injection/ads
  → Final output
```

### Fallback Chain

1. readability-lxml on `cleaned_html` or `html` field
2. If readability output < 200 chars → fall back to Crawl4AI's `fit_markdown` / `raw_markdown`
3. If markdown still noisy → `clean_markdown()` filters by link density and boilerplate patterns

---

## Layer 1: HTML Main Content Extraction

**New file:** `gateway/content_extractor.py`

### readability-lxml Integration

- Input: raw HTML string from Crawl4AI response
- Use `readability.Document(html).summary()` to extract `<article>` main body
- readability auto-removes: `<nav>`, `<footer>`, `<aside>`, `<header>`, sidebars, ad containers, cookie banners
- Extract title via `readability.Document(html).title()`

### html_to_markdown Conversion

Convert readability's clean HTML output to markdown:

| HTML | Markdown |
|------|----------|
| `<h1>`–`<h6>` | `#`–`######` |
| `<p>` | paragraph with blank line |
| `<a href="url">text</a>` | `[text](url)` |
| `<strong>`, `<b>` | `**text**` |
| `<em>`, `<i>` | `*text*` |
| `<ul>/<li>` | `- item` |
| `<ol>/<li>` | `1. item` |
| `<table>` | markdown table |
| `<blockquote>` | `> text` |
| `<code>` | `` `code` `` |
| `<pre>` | ``` code block ``` |
| `<img>` | `![alt](src)` |
| `<br>` | newline |

Use BeautifulSoup (already a dependency) for HTML parsing. No new dependencies.

### Function Signature

```python
def extract_main_content(html: str) -> tuple[str | None, str | None]:
    """Extract main content from HTML using readability.

    Returns (markdown_content, title). Returns (None, None) on failure.
    """
```

---

## Layer 2: Markdown Post-Processing

**Modified file:** `gateway/sanitizer.py` — add `clean_markdown()` function.

### Stage 1: Link Density Filtering

Split markdown into blocks (by double newline). For each block:

```
link_density = total_chars_inside_[text](url) / total_chars_in_block
```

- `link_density > 0.5` → remove block (navigation)
- Block < 80 chars AND `link_density > 0.3` → remove block

### Stage 2: Consecutive Link Detection

Detect 3+ consecutive lines matching menu patterns:

```
* [text](url)
- [text](url)
[text](url) | [text](url)
```

Remove entire consecutive-link groups.

### Stage 3: Short Block Context Analysis (jusText method)

After stages 1–2, classify remaining blocks:
- **good**: length >= 80 chars AND link_density < 0.3
- **bad**: already removed or link_density > 0.5
- **uncertain**: everything else

For uncertain blocks:
- Between two good blocks → keep
- Between two bad blocks → remove
- Adjacent to good → keep
- Isolated → remove

### Stage 4: Boilerplate Keyword Filtering

Remove blocks containing boilerplate patterns:

**Chinese:** 隱私權政策, Cookie政策, 關於我們, 聯絡我們, 客服中心, 登入/註冊, 回到頂部, 下載App, 服務條款, 使用條款, 著作權, 版權所有, 意見回饋, 訂閱電子報, 追蹤我們, 分享至, 加入書籤, 檢舉, 場地租借

**English:** Privacy Policy, Terms of Service, Cookie, About Us, Contact Us, Sign In, Sign Up, Back to Top, Download App, Subscribe, Follow Us, Share, Copyright, All Rights Reserved

### Stage 5: Optional Link Stripping

When `strip_links=True`:
- `[text](url)` → `text`
- `![alt](src)` → (remove entirely or keep alt text)

### Function Signature

```python
def clean_markdown(
    text: str,
    strip_links: bool = False,
    link_density_threshold: float = 0.5,
    min_block_length: int = 80,
) -> str:
    """Remove navigation, boilerplate, and noise from markdown content."""
```

---

## Integration Points

### crawl_client.py Changes

In `crawl_url()`, after extracting content from Crawl4AI response:

1. If HTML is available (`cleaned_html` or `html` field), run `extract_main_content(html)`
2. If readability succeeds (content >= 200 chars), use readability markdown as primary content
3. Apply `clean_markdown()` on the result
4. Then apply existing `sanitize_content()` for injection/ad filtering

### models.py Changes

Add to `SearchRequest`:
```python
stripLinks: bool = False
```

Add to `CrawlRequest`:
```python
stripLinks: bool = False
```

### app.py Changes

Pass `strip_links` parameter through the crawl pipeline.

---

## File Changes Summary

| File | Change Type | Description |
|------|------------|-------------|
| `gateway/content_extractor.py` | **New** | readability extraction + html→markdown |
| `gateway/sanitizer.py` | **Modify** | Add `clean_markdown()` with 5-stage pipeline |
| `gateway/crawl_client.py` | **Modify** | Integrate dual-layer cleaning into crawl pipeline |
| `gateway/models.py` | **Modify** | Add `stripLinks` to SearchRequest/CrawlRequest |
| `gateway/app.py` | **Modify** | Pass stripLinks through pipeline |
| `tests/test_content_extractor.py` | **New** | Tests for readability extraction |
| `tests/test_sanitizer.py` | **Modify** | Add tests for clean_markdown() |

## No New Dependencies

- `readability-lxml` — already in pyproject.toml
- `beautifulsoup4` — already in pyproject.toml
