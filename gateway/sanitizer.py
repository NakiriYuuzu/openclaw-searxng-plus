import html
import logging
import re
import unicodedata
from pathlib import Path

try:
    import bleach

    _HAS_BLEACH = True
except ImportError:
    _HAS_BLEACH = False

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bot / anti-crawl detection
# ---------------------------------------------------------------------------
_BOT_DETECTION_PATTERNS = [
    re.compile(r"security\s*verification", re.IGNORECASE),
    re.compile(r"verif(?:y|ying)\s+(?:you\s+are\s+)?(?:not\s+)?(?:a\s+)?(?:bot|robot|human)", re.IGNORECASE),
    re.compile(r"checking\s+(?:if\s+)?(?:the\s+)?site\s+connection\s+is\s+secure", re.IGNORECASE),
    re.compile(r"enable\s+javascript\s+(?:and\s+cookies\s+)?to\s+continue", re.IGNORECASE),
    re.compile(r"access\s+(?:to\s+)?this\s+(?:page|site)\s+has\s+been\s+denied", re.IGNORECASE),
    re.compile(r"cloudflare|hcaptcha|recaptcha", re.IGNORECASE),
    re.compile(r"just\s+a\s+moment.*?(?:please\s+wait|loading)", re.IGNORECASE | re.DOTALL),
    re.compile(r"請\s*完成\s*(?:安全\s*)?驗證", re.IGNORECASE),
    re.compile(r"ray\s*id\s*:", re.IGNORECASE),
    re.compile(r"please\s+(?:enable|turn\s+on)\s+javascript", re.IGNORECASE),
]

# Domains known to block crawlers or require JS rendering
CRAWL_SKIP_DOMAINS = frozenset({
    # Chinese platforms (heavy JS + anti-crawl)
    "www.zhihu.com", "zhihu.com",
    "zhuanlan.zhihu.com",
    "zhidao.baidu.com",
    "tieba.baidu.com",
    "www.xiaohongshu.com",
    "weibo.com", "www.weibo.com",
    "mp.weixin.qq.com",
    "www.bilibili.com",
    "www.douyin.com",
    # Social platforms
    "twitter.com", "x.com",
    "www.facebook.com", "facebook.com",
    "www.instagram.com",
    "www.tiktok.com",
    "www.linkedin.com",
    # Others with aggressive anti-bot
    "www.quora.com",
})


def is_bot_detection_page(content: str) -> bool:
    """Detect if content is a bot verification / CAPTCHA / anti-crawl page."""
    if not content or len(content.strip()) < 50:
        return False
    # Short content that matches bot patterns is very likely a verification page
    text = content.strip()
    if len(text) < 500:
        for pattern in _BOT_DETECTION_PATTERNS:
            if pattern.search(text):
                return True
    return False


def should_skip_crawl(domain: str) -> bool:
    """Check if a domain should be skipped for crawling."""
    return domain.lower() in CRAWL_SKIP_DOMAINS


_INJECTION_PATTERNS = [
    re.compile(r"<\s*/?\s*system\s*>", re.IGNORECASE),
    re.compile(r"<\s*/?\s*assistant\s*>", re.IGNORECASE),
    re.compile(r"<\s*/?\s*human\s*>", re.IGNORECASE),
    re.compile(r"<\s*/?\s*user\s*>", re.IGNORECASE),
    re.compile(r"\bignore\s+(all\s+)?previous\s+instructions\b", re.IGNORECASE),
    re.compile(r"\byou\s+are\s+now\b", re.IGNORECASE),
    re.compile(r"\bact\s+as\s+(an?\s+)?(admin|root|system)\b", re.IGNORECASE),
    re.compile(r"\[SYSTEM\]", re.IGNORECASE),
    re.compile(r"```\s*system\b", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# Ad pattern loading — external file with hardcoded fallback
# ---------------------------------------------------------------------------
_DEFAULT_AD_PATTERNS = [
    re.compile(r"(廣告|贊助|推薦連結|業配|sponsored|promoted|advertisement)", re.IGNORECASE),
    re.compile(r"\b(aff|affiliate|partner|tracking|utm_\w+|ref|campaign)(\?|=)", re.IGNORECASE),
    re.compile(r"(立即購買|點此領取|限時優惠|免費試用)", re.IGNORECASE),
    re.compile(r"(立即申辦|馬上申請|立即開通|立即體驗)", re.IGNORECASE),
    re.compile(r"(立即下載|掃描立即下載|下載App)", re.IGNORECASE),
    re.compile(r"(buy now|click here|free trial|limited offer)", re.IGNORECASE),
    re.compile(r"(sign up now|download now|get started free)", re.IGNORECASE),
]

_MAX_PATTERN_LENGTH = 500


def _load_ad_patterns() -> list[re.Pattern]:
    patterns: list[re.Pattern] = []
    path = Path(__file__).parent.parent / "config" / "ad_patterns.txt"
    if path.exists():
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if line and not line.startswith("#"):
                if len(line) > _MAX_PATTERN_LENGTH:
                    logger.warning("Ad pattern too long at line %d, skipping", line_no)
                    continue
                try:
                    compiled = re.compile(line, re.IGNORECASE)
                    compiled.search("validation test")
                    patterns.append(compiled)
                except re.error as exc:
                    logger.warning("Invalid regex at line %d: %s", line_no, exc)
                    continue
    return patterns or _DEFAULT_AD_PATTERNS


_AD_PATTERNS = _load_ad_patterns()

# Pre-compile combined ad pattern for efficient matching
_COMBINED_AD_PATTERN = re.compile(
    "|".join(f"({p.pattern})" for p in _AD_PATTERNS),
    re.IGNORECASE,
)

# Pre-compile segment split pattern
_SEGMENT_SPLIT_RE = re.compile(r"(?<=[。.!！?？\n])\s*|(?:\s*[·\u00b7\u30fb]\s*)")


def _normalize_for_injection_check(text: str) -> str:
    """Remove zero-width and invisible Unicode characters for injection detection."""
    text = "".join(
        ch for ch in text if unicodedata.category(ch) not in ("Mn", "Me", "Cf")
    )
    text = re.sub(r"\s+", " ", text)
    return text


def _remove_ad_segments(text: str) -> str:
    """Remove paragraphs/sentences that match ad patterns."""
    segments = _SEGMENT_SPLIT_RE.split(text)
    cleaned = []
    for segment in segments:
        if not segment.strip():
            continue
        if not _COMBINED_AD_PATTERN.search(segment):
            cleaned.append(segment)
    return " ".join(cleaned) if cleaned else text


def sanitize_content(text: str, max_length: int = 50000) -> str:
    """Strip HTML, filter prompt-injection artifacts, remove ads, normalize whitespace, truncate."""
    if not text:
        return ""

    # Decode HTML entities BEFORE filtering so &lt;system&gt; is caught
    text = html.unescape(text)

    # Normalize for injection detection (zero-width chars, etc.)
    normalized = _normalize_for_injection_check(text)
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(normalized):
            # Apply filter on both normalized and original text
            text = _normalize_for_injection_check(text)
            text = pattern.sub("[FILTERED]", text)
            break  # Re-normalize then re-check all patterns

    # Re-run all patterns on the (possibly normalized) text
    for pattern in _INJECTION_PATTERNS:
        text = pattern.sub("[FILTERED]", text)

    if _HAS_BLEACH:
        text = bleach.clean(text, tags=[], strip=True)
    else:
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"&[a-zA-Z]+;", " ", text)

    # Remove ad segments
    text = _remove_ad_segments(text)

    text = re.sub(r"\s+", " ", text).strip()

    if len(text) > max_length:
        truncated = text[:max_length]
        last_space = truncated.rfind(" ")
        if last_space > max_length * 0.8:
            truncated = truncated[:last_space]
        text = truncated.rstrip() + "..."

    return text


# ---------------------------------------------------------------------------
# Markdown content cleaning (post-crawl)
# ---------------------------------------------------------------------------
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]+\)")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
_LIST_LINK_RE = re.compile(r"^\s*[-*]\s*\[([^\]]*)\]\([^)]+\)\s*$")
_LINK_LINE_RE = re.compile(r"^\s*\[([^\]]*)\]\([^)]+\)\s*$")

_BOILERPLATE_PATTERNS = re.compile(
    r"("
    # Chinese nav/footer
    r"隱私權政策|Cookie\s*政策|關於我們|聯絡我們|客服中心"
    r"|登入[/／]註冊|登入\s*註冊|回到頂部|下載\s*App"
    r"|服務條款|使用條款|版權所有|著作權"
    r"|訂閱電子報|追蹤我們|分享至|加入書籤"
    r"|場地租借|意見回饋|檢舉|成為.*作者"
    r"|加入我們|回報問題|意見反饋"
    # Chinese promotional
    r"|立即免費探索|免費體驗|立即體驗|免費試用"
    r"|立即開始|立即加入|馬上體驗|立即探索"
    # English nav/footer
    r"|Privacy\s*Policy|Terms\s*of\s*Service|Cookie\s*Policy"
    r"|About\s*Us|Contact\s*Us|Sign\s*In|Sign\s*Up"
    r"|Back\s*to\s*Top|Download\s*App|Subscribe\s*Now"
    r"|Follow\s*Us|Share\s*this|Newsletter|Unsubscribe"
    r"|All\s*Rights?\s*Reserved|©\s*\d{4}"
    r"|Report\s*(?:a\s*)?Bug|Join\s*Us|Careers"
    r"|Powered\s*by|Built\s*with"
    r")",
    re.IGNORECASE,
)

# Pattern to fix broken decimal numbers (e.g., "47242. 52" → "47242.52")
_BROKEN_DECIMAL_RE = re.compile(r"(\d+)\.\s+(\d+)")


def _calc_link_density(text: str) -> float:
    """Calculate the ratio of link text to total text in a block."""
    if not text.strip():
        return 0.0
    total_len = len(text.strip())
    if total_len == 0:
        return 0.0
    link_chars = sum(len(m.group(0)) for m in _LINK_RE.finditer(text))
    link_chars += sum(len(m.group(0)) for m in _IMAGE_RE.finditer(text))
    return link_chars / total_len


def _effective_link_threshold(block: str, base_threshold: float) -> float:
    """Adaptive link density threshold: prose-heavy blocks get more tolerance."""
    stripped = block.strip()
    block_len = len(stripped)

    # Long blocks with prose patterns get higher threshold (content links are ok)
    if block_len > 300:
        return min(base_threshold + 0.25, 0.85)
    if block_len > 150:
        return min(base_threshold + 0.15, 0.75)
    return base_threshold


def _is_link_line(line: str) -> bool:
    """Check if a line is primarily a link (list link or standalone link)."""
    stripped = line.strip()
    if not stripped:
        return False
    if _LIST_LINK_RE.match(stripped):
        return True
    if _LINK_LINE_RE.match(stripped):
        return True
    # Check if line is > 80% links
    link_chars = sum(len(m.group(0)) for m in _LINK_RE.finditer(stripped))
    return len(stripped) > 0 and link_chars / len(stripped) > 0.8


def _remove_consecutive_links(text: str, min_consecutive: int = 3) -> str:
    """Remove groups of 3+ consecutive lines that are primarily links."""
    lines = text.split("\n")
    result = []
    link_group: list[int] = []

    for i, line in enumerate(lines):
        if _is_link_line(line):
            link_group.append(i)
        else:
            if len(link_group) >= min_consecutive:
                # Don't add these lines — they're navigation
                pass
            else:
                # Flush the small link group (keep them)
                for idx in link_group:
                    result.append(lines[idx])
            link_group = []
            result.append(line)

    # Handle trailing group
    if len(link_group) >= min_consecutive:
        pass
    else:
        for idx in link_group:
            result.append(lines[idx])

    return "\n".join(result)


def clean_markdown(
    text: str,
    strip_links: bool = False,
    link_density_threshold: float = 0.5,
    min_block_length: int = 80,
) -> str:
    """Remove navigation, boilerplate, and noise from markdown content.

    Five-stage pipeline:
    1. Link density filtering per block
    2. Consecutive link line detection and removal
    3. Short block context analysis (jusText method)
    4. Boilerplate keyword filtering
    5. Optional link stripping
    """
    if not text or not text.strip():
        return ""

    # Stage 2: Remove consecutive link lines first (works on raw lines)
    text = _remove_consecutive_links(text)

    # Split into blocks
    blocks = re.split(r"\n\s*\n", text)

    # Stage 1 + classify blocks
    classifications: list[str] = []  # "good", "bad", "uncertain"
    for block in blocks:
        stripped = block.strip()
        if not stripped:
            classifications.append("bad")
            continue

        density = _calc_link_density(stripped)
        block_len = len(stripped)

        # Stage 4: Boilerplate keyword check
        if _BOILERPLATE_PATTERNS.search(stripped):
            classifications.append("bad")
            continue

        # Stage 1: Link density filtering (adaptive threshold)
        effective_threshold = _effective_link_threshold(stripped, link_density_threshold)
        if density > effective_threshold:
            classifications.append("bad")
            continue

        if block_len < min_block_length and density > 0.3:
            classifications.append("bad")
            continue

        # Classify
        if block_len >= min_block_length and density < 0.3:
            classifications.append("good")
        else:
            classifications.append("uncertain")

    # Stage 3: Context-sensitive reclassification
    for i, cls in enumerate(classifications):
        if cls != "uncertain":
            continue

        prev_cls = None
        next_cls = None
        for j in range(i - 1, -1, -1):
            if classifications[j] != "uncertain":
                prev_cls = classifications[j]
                break
        for j in range(i + 1, len(classifications)):
            if classifications[j] != "uncertain":
                next_cls = classifications[j]
                break

        if prev_cls == "good" or next_cls == "good":
            classifications[i] = "good"
        elif prev_cls == "bad" and next_cls == "bad":
            classifications[i] = "bad"
        else:
            # Default: keep if not surrounded by bad
            classifications[i] = "good"

    # Rebuild text from good blocks
    cleaned_blocks = []
    for block, cls in zip(blocks, classifications):
        if cls == "good":
            cleaned_blocks.append(block.strip())

    result = "\n\n".join(cleaned_blocks)

    # Stage 5: Optional link stripping
    if strip_links:
        result = _IMAGE_RE.sub("", result)  # Remove images entirely
        result = _LINK_RE.sub(r"\1", result)  # [text](url) → text

    # Fix broken decimal numbers (e.g., "47242. 52" → "47242.52")
    result = _BROKEN_DECIMAL_RE.sub(r"\1.\2", result)

    # Final whitespace cleanup
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()
