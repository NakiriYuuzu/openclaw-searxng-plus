import pytest

from gateway.content_extractor import extract_main_content, _html_to_markdown


ARTICLE_HTML = """
<html>
<head><title>Test Article Title</title></head>
<body>
<nav>
    <a href="/">Home</a>
    <a href="/about">About</a>
    <a href="/contact">Contact</a>
</nav>
<header>
    <div class="logo">Site Logo</div>
    <div class="menu">Menu items here</div>
</header>
<article>
    <h1>Main Article Title</h1>
    <p>This is the first paragraph of the main article content. It contains important information
    that should be preserved in the extraction process. This paragraph is long enough to pass
    the minimum content length threshold for readability extraction.</p>
    <p>This is the second paragraph with more detailed content about the topic being discussed.
    It provides additional context and information that readers would find valuable.</p>
    <h2>Section Two</h2>
    <p>Another section with substantial content that demonstrates the extraction of multi-section
    articles. This content should be properly converted to markdown format with correct heading
    levels and paragraph breaks.</p>
    <table>
        <tr><th>Stock</th><th>Price</th><th>Change</th></tr>
        <tr><td>TSMC</td><td>1865</td><td>-1.06%</td></tr>
        <tr><td>MediaTek</td><td>1720</td><td>-3.64%</td></tr>
    </table>
    <ul>
        <li>First point about market trends</li>
        <li>Second point about investment strategy</li>
        <li>Third point about risk management</li>
    </ul>
    <p>Final concluding paragraph with a <a href="https://example.com">reference link</a>
    and some <strong>bold text</strong> and <em>italic text</em> for formatting.</p>
</article>
<footer>
    <p>Copyright 2026 Example Corp</p>
    <a href="/privacy">Privacy Policy</a>
    <a href="/terms">Terms of Service</a>
</footer>
</body>
</html>
"""

NAV_HEAVY_HTML = """
<html>
<body>
<div id="sidebar">
    <a href="/page1">Page 1</a>
    <a href="/page2">Page 2</a>
    <a href="/page3">Page 3</a>
    <a href="/page4">Page 4</a>
    <a href="/page5">Page 5</a>
    <a href="/page6">Page 6</a>
    <a href="/page7">Page 7</a>
    <a href="/page8">Page 8</a>
    <a href="/page9">Page 9</a>
    <a href="/page10">Page 10</a>
</div>
<div id="content">
    <h1>Article in Nav Heavy Page</h1>
    <p>This is the main content of the page. It should be extracted even though there are
    many navigation links surrounding it. The readability algorithm should identify this
    as the main content area based on text density analysis. This paragraph contains enough
    text to be considered a proper content block.</p>
    <p>A second paragraph adds more content weight to this section, making it easier for
    the readability algorithm to correctly identify this as the main content of the page
    rather than the navigation sidebar.</p>
</div>
</body>
</html>
"""

MINIMAL_HTML = "<html><body><p>Too short</p></body></html>"

EMPTY_HTML = ""


class TestExtractMainContent:
    def test_extracts_article_content(self):
        markdown, title = extract_main_content(ARTICLE_HTML)
        assert markdown is not None
        assert title is not None
        assert "Main Article Title" in markdown
        assert "first paragraph" in markdown
        assert "Section Two" in markdown

    def test_preserves_table(self):
        markdown, _ = extract_main_content(ARTICLE_HTML)
        assert markdown is not None
        assert "TSMC" in markdown
        assert "1865" in markdown

    def test_preserves_list(self):
        markdown, _ = extract_main_content(ARTICLE_HTML)
        assert markdown is not None
        assert "market trends" in markdown

    def test_preserves_formatting(self):
        markdown, _ = extract_main_content(ARTICLE_HTML)
        assert markdown is not None
        assert "**bold text**" in markdown
        assert "*italic text*" in markdown

    def test_preserves_links(self):
        markdown, _ = extract_main_content(ARTICLE_HTML)
        assert markdown is not None
        assert "[reference link](https://example.com)" in markdown

    def test_removes_nav_footer(self):
        markdown, _ = extract_main_content(ARTICLE_HTML)
        assert markdown is not None
        # Nav and footer content should not appear
        assert "Privacy Policy" not in markdown
        assert "Terms of Service" not in markdown

    def test_handles_nav_heavy_page(self):
        markdown, _ = extract_main_content(NAV_HEAVY_HTML)
        assert markdown is not None
        assert "main content" in markdown

    def test_returns_none_for_short_content(self):
        markdown, title = extract_main_content(MINIMAL_HTML)
        assert markdown is None

    def test_returns_none_for_empty(self):
        markdown, title = extract_main_content(EMPTY_HTML)
        assert markdown is None

    def test_returns_none_for_none(self):
        markdown, title = extract_main_content(None)
        assert markdown is None


class TestHtmlToMarkdown:
    def test_headings(self):
        html = "<h1>Title</h1><h2>Subtitle</h2><h3>Section</h3>"
        md = _html_to_markdown(html)
        assert "# Title" in md
        assert "## Subtitle" in md
        assert "### Section" in md

    def test_paragraphs(self):
        html = "<p>First paragraph.</p><p>Second paragraph.</p>"
        md = _html_to_markdown(html)
        assert "First paragraph." in md
        assert "Second paragraph." in md

    def test_links(self):
        html = '<p><a href="https://example.com">Click here</a></p>'
        md = _html_to_markdown(html)
        assert "[Click here](https://example.com)" in md

    def test_skips_javascript_links(self):
        html = '<p><a href="javascript:void(0)">Bad link</a></p>'
        md = _html_to_markdown(html)
        assert "javascript:" not in md
        assert "Bad link" in md

    def test_bold_italic(self):
        html = "<p><strong>Bold</strong> and <em>italic</em></p>"
        md = _html_to_markdown(html)
        assert "**Bold**" in md
        assert "*italic*" in md

    def test_unordered_list(self):
        html = "<ul><li>Item 1</li><li>Item 2</li></ul>"
        md = _html_to_markdown(html)
        assert "- Item 1" in md
        assert "- Item 2" in md

    def test_ordered_list(self):
        html = "<ol><li>First</li><li>Second</li></ol>"
        md = _html_to_markdown(html)
        assert "1. First" in md
        assert "2. Second" in md

    def test_table(self):
        html = "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
        md = _html_to_markdown(html)
        assert "| A | B |" in md
        assert "| 1 | 2 |" in md
        assert "---" in md

    def test_blockquote(self):
        html = "<blockquote>Quoted text</blockquote>"
        md = _html_to_markdown(html)
        assert "> Quoted text" in md

    def test_code_block(self):
        html = "<pre><code>print('hello')</code></pre>"
        md = _html_to_markdown(html)
        assert "```" in md
        assert "print('hello')" in md

    def test_inline_code(self):
        html = "<p>Use <code>pip install</code> to install</p>"
        md = _html_to_markdown(html)
        assert "`pip install`" in md

    def test_image(self):
        html = '<img alt="Photo" src="https://example.com/img.jpg">'
        md = _html_to_markdown(html)
        assert "![Photo](https://example.com/img.jpg)" in md

    def test_strips_scripts(self):
        html = "<div><script>alert('xss')</script><p>Content</p></div>"
        md = _html_to_markdown(html)
        assert "alert" not in md
        assert "Content" in md

    def test_normalizes_whitespace(self):
        html = "<p>Text</p>\n\n\n\n<p>More text</p>"
        md = _html_to_markdown(html)
        assert "\n\n\n" not in md
