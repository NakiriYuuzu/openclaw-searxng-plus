from difflib import SequenceMatcher

TITLE_SIMILARITY_THRESHOLD = 0.85


def deduplicate(results: list[dict]) -> list[dict]:
    """
    Deduplicate results by URL (exact) and title (fuzzy).
    Merges engine lists and accumulates scores for duplicates.
    """
    seen_urls: dict[str, int] = {}
    deduped: list[dict] = []

    for result in results:
        url = result["url"]

        # Exact URL dedup
        if url in seen_urls:
            existing = deduped[seen_urls[url]]
            _merge_into(existing, result)
            continue

        # Fuzzy title dedup
        matched = False
        for existing in deduped:
            ratio = SequenceMatcher(
                None,
                result["title"].lower(),
                existing["title"].lower(),
            ).ratio()
            if ratio >= TITLE_SIMILARITY_THRESHOLD:
                _merge_into(existing, result)
                matched = True
                break

        if not matched:
            seen_urls[url] = len(deduped)
            deduped.append(result)

    return deduped


def _merge_into(existing: dict, incoming: dict) -> None:
    """Merge incoming result data into existing result."""
    for eng in incoming.get("engines", []):
        if eng not in existing.get("engines", []):
            existing.setdefault("engines", []).append(eng)

    if len(incoming.get("snippet", "")) > len(existing.get("snippet", "")):
        existing["snippet"] = incoming["snippet"]

    existing["score"] = existing.get("score", 0) + incoming.get("score", 0)
