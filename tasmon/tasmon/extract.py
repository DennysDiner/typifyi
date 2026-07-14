"""Full-text extraction for Tier 1 articles via trafilatura."""


def extract_text(html: str, url: str = None) -> str | None:
    try:
        import trafilatura
    except ImportError:
        return None
    try:
        return trafilatura.extract(html, url=url, include_comments=False)
    except Exception:
        return None


def extract_title(html: str) -> str | None:
    try:
        import trafilatura
        meta = trafilatura.extract_metadata(html)
        return meta.title if meta else None
    except Exception:
        return None
