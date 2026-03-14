import logging
import re

from bs4 import BeautifulSoup, NavigableString, Tag
from readability import Document

logger = logging.getLogger(__name__)

_MIN_CONTENT_LENGTH = 200


def _is_inside_pre(element) -> bool:
    """Check if an element is inside a <pre> tag."""
    parent = element.parent
    while parent:
        if isinstance(parent, Tag) and parent.name == "pre":
            return True
        parent = parent.parent
    return False


def extract_main_content(html: str) -> tuple[str | None, str | None]:
    """Extract main content from HTML using readability-lxml.

    Returns (markdown_content, title). Returns (None, None) on failure.
    """
    if not html or len(html.strip()) < 100:
        return None, None

    try:
        doc = Document(html)
        title = doc.title()
        summary_html = doc.summary()

        if not summary_html:
            return None, None

        markdown = _html_to_markdown(summary_html)

        if not markdown or len(markdown.strip()) < _MIN_CONTENT_LENGTH:
            return None, None

        return markdown.strip(), title
    except Exception:
        logger.debug("Readability extraction failed", exc_info=True)
        return None, None


def _html_to_markdown(html: str) -> str:
    """Convert clean HTML to markdown."""
    soup = BeautifulSoup(html, "html.parser")
    result = _convert_element(soup)
    # Normalize multiple blank lines
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def _convert_element(element) -> str:
    """Recursively convert an HTML element to markdown."""
    if isinstance(element, NavigableString):
        text = str(element)
        # Preserve whitespace inside <pre> elements
        if _is_inside_pre(element):
            return text
        # Collapse whitespace in inline text
        text = re.sub(r"[ \t]+", " ", text)
        return text

    if not isinstance(element, Tag):
        return ""

    tag = element.name
    if tag is None:
        # Document node or other non-tag
        return "".join(_convert_element(child) for child in element.children)

    # Skip script, style, nav, footer, aside
    if tag in ("script", "style", "nav", "footer", "aside", "noscript"):
        return ""

    # Headings
    if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        level = int(tag[1])
        inner = _inline_text(element)
        if inner.strip():
            return f"\n\n{'#' * level} {inner.strip()}\n\n"
        return ""

    # Paragraph
    if tag == "p":
        inner = _inline_content(element)
        if inner.strip():
            return f"\n\n{inner.strip()}\n\n"
        return ""

    # Links
    if tag == "a":
        href = element.get("href", "")
        if not href or href.startswith(("#", "javascript:")):
            return _inline_content(element)
        text = _inline_text(element)
        if text.strip():
            return f"[{text.strip()}]({href})"
        return ""

    # Bold
    if tag in ("strong", "b"):
        inner = _inline_content(element)
        if inner.strip():
            return f"**{inner.strip()}**"
        return ""

    # Italic
    if tag in ("em", "i"):
        inner = _inline_content(element)
        if inner.strip():
            return f"*{inner.strip()}*"
        return ""

    # Code (inline)
    if tag == "code" and (not element.parent or element.parent.name != "pre"):
        inner = element.get_text()
        if inner.strip():
            return f"`{inner.strip()}`"
        return ""

    # Pre / code block
    if tag == "pre":
        code = element.get_text()
        if code.strip():
            return f"\n\n```\n{code.strip()}\n```\n\n"
        return ""

    # Blockquote
    if tag == "blockquote":
        inner = _inline_content(element)
        if inner.strip():
            lines = inner.strip().split("\n")
            quoted = "\n".join(f"> {line}" for line in lines)
            return f"\n\n{quoted}\n\n"
        return ""

    # Unordered list
    if tag == "ul":
        items = []
        for li in element.find_all("li", recursive=False):
            item_text = _inline_content(li).strip()
            if item_text:
                items.append(f"- {item_text}")
        if items:
            return "\n\n" + "\n".join(items) + "\n\n"
        return ""

    # Ordered list
    if tag == "ol":
        items = []
        for idx, li in enumerate(element.find_all("li", recursive=False), 1):
            item_text = _inline_content(li).strip()
            if item_text:
                items.append(f"{idx}. {item_text}")
        if items:
            return "\n\n" + "\n".join(items) + "\n\n"
        return ""

    # Table
    if tag == "table":
        return _convert_table(element)

    # Image
    if tag == "img":
        alt = element.get("alt", "")
        src = element.get("src", "")
        if src:
            return f"![{alt}]({src})"
        return ""

    # Line break
    if tag == "br":
        return "\n"

    # Horizontal rule
    if tag == "hr":
        return "\n\n---\n\n"

    # Div, section, article, main, span — recurse into children
    if tag in ("div", "section", "article", "main", "span", "figure", "figcaption",
               "details", "summary", "mark", "small", "sup", "sub", "abbr",
               "time", "header", "body", "html", "[document]"):
        return "".join(_convert_element(child) for child in element.children)

    # Default: recurse into children
    return "".join(_convert_element(child) for child in element.children)


def _inline_content(element) -> str:
    """Get inline content of an element (preserving markdown formatting)."""
    return "".join(_convert_element(child) for child in element.children)


def _inline_text(element) -> str:
    """Get plain text content of an element."""
    return element.get_text()


def _convert_table(table) -> str:
    """Convert an HTML table to markdown table."""
    rows = []
    for tr in table.find_all("tr"):
        cells = []
        for cell in tr.find_all(["th", "td"]):
            cell_text = _inline_text(cell).strip()
            # Replace pipe characters and newlines in cell text
            cell_text = cell_text.replace("|", "\\|").replace("\n", " ")
            cells.append(cell_text)
        if cells:
            rows.append(cells)

    if not rows:
        return ""

    # Determine column count
    max_cols = max(len(row) for row in rows)

    # Pad rows to same length
    for row in rows:
        while len(row) < max_cols:
            row.append("")

    # Build markdown table
    lines = []
    # First row as header
    lines.append("| " + " | ".join(rows[0]) + " |")
    lines.append("| " + " | ".join("---" for _ in range(max_cols)) + " |")
    # Remaining rows
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")

    return "\n\n" + "\n".join(lines) + "\n\n"
