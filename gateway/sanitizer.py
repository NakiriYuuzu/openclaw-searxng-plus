import re

try:
    import bleach

    _HAS_BLEACH = True
except ImportError:
    _HAS_BLEACH = False

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


def sanitize_content(text: str, max_length: int = 50000) -> str:
    """Strip HTML, filter prompt-injection artifacts, normalize whitespace, truncate."""
    if not text:
        return ""

    # Filter prompt-injection patterns BEFORE stripping HTML
    # so that tags like <system> are caught before bleach removes them
    for pattern in _INJECTION_PATTERNS:
        text = pattern.sub("[FILTERED]", text)

    if _HAS_BLEACH:
        text = bleach.clean(text, tags=[], strip=True)
    else:
        text = re.sub(r"<[^>]+>", " ", text)

    text = re.sub(r"\s+", " ", text).strip()

    if len(text) > max_length:
        text = text[:max_length] + "..."

    return text
