"""Normalisation: strip volatile content *before* hashing (§2.3).

This is the most important module in the project. If it strips too little, every
run reports false changes; if it strips too much, a real change is missed. Every
rule here is narrow, named, and covered by a fixture test in
``tests/test_normalise.py``.

Two rules of thumb kept the list honest:

* Only content that changes *without the publisher changing anything* may be
  stripped (session ids, CSRF tokens, cache-busting query strings, render
  timestamps, ad slots).
* Anything a publisher could have meant — "last updated", amounts, dates in the
  body — is never stripped, even when it looks incidental.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Comment

# --- URL canonicalisation ---------------------------------------------------

# Query parameters that identify a session or defeat a cache, never content.
VOLATILE_QUERY_PARAMS: frozenset[str] = frozenset(
    {
        "jsessionid",
        "phpsessid",
        "sessionid",
        "session_id",
        "sid",
        "aspsessionid",
        "csrf",
        "csrf_token",
        "csrftoken",
        "authenticity_token",
        "__requestverificationtoken",
        "_",
        "cb",
        "cachebuster",
        "cache_buster",
        "nocache",
        "timestamp",
        "ts",
        "rnd",
        "random",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "gclid",
        "fbclid",
    }
)

DEFAULT_PORTS = {"http": "80", "https": "443"}


def canonical_url(url: str, *, keep_fragment: bool = False) -> str:
    """Canonicalise a URL for hashing and identity.

    Lowercases scheme and host, drops the default port, removes volatile query
    parameters, sorts the remainder, and drops the fragment. Path case is
    preserved: many government sites are case-sensitive.
    """
    if not url:
        return url
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = parts.hostname or ""
    netloc = host.lower()
    if parts.port and str(parts.port) != DEFAULT_PORTS.get(scheme):
        netloc = f"{netloc}:{parts.port}"
    if parts.username:
        auth = parts.username + (f":{parts.password}" if parts.password else "")
        netloc = f"{auth}@{netloc}"
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in VOLATILE_QUERY_PARAMS
    ]
    query = "&".join(f"{key}={value}" for key, value in sorted(query_pairs))
    fragment = parts.fragment if keep_fragment else ""
    path = parts.path
    # ``/a/b/;jsessionid=XYZ`` style path parameters.
    path = re.sub(r";(?i:jsessionid|phpsessid|sessionid)=[^/;?]*", "", path)
    return urlunsplit((scheme, netloc, path, query, fragment))


# --- Volatile text ----------------------------------------------------------

_TIMESTAMPISH = r"[0-9]{1,4}[-/ :.][0-9A-Za-z]{1,9}[-/ :.][0-9]{1,4}(?:[ T][0-9:.]{4,12})?(?:\s*(?:[AaPp]\.?[Mm]\.?|UTC|GMT|AEST|AEDT|[+-][0-9:]{4,5}))?"

VOLATILE_TEXT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "session_id",
        re.compile(
            r"(?i)\b(?:jsessionid|phpsessid|asp\.net_sessionid|sessionid|session[_ ]id)"
            r"\s*[=:]\s*[A-Za-z0-9%._-]{6,}"
        ),
    ),
    (
        "csrf_token",
        re.compile(
            r"(?i)\b(?:csrf[_ -]?token|authenticity[_ ]token|request[_ ]?verification[_ ]?token"
            r"|anti[_ -]?forgery(?:[_ ]token)?|xsrf[_ -]?token)\s*[=:]\s*[\"']?[A-Za-z0-9+/=_.-]{8,}"
        ),
    ),
    ("viewstate", re.compile(r"(?i)\b__(?:VIEWSTATE|EVENTVALIDATION|VIEWSTATEGENERATOR)\S*")),
    ("nonce", re.compile(r"(?i)\bnonce\s*[=:]\s*[\"']?[A-Za-z0-9+/=_-]{8,}")),
    (
        "render_timestamp",
        re.compile(
            r"(?i)\b(?:generated|rendered|produced|printed|retrieved|downloaded|extracted)"
            r"\s*(?:on|at|:)?\s*" + _TIMESTAMPISH
        ),
    ),
    (
        "page_current_datetime",
        re.compile(
            r"(?i)\b(?:current(?:\s+date(?:\s*/?\s*time)?|\s+time)|today(?:'s)?\s+date|date\s+accessed"
            r"|accessed\s+on|time\s+now)\s*(?:is|:)?\s*" + _TIMESTAMPISH
        ),
    ),
    (
        "render_duration",
        re.compile(r"(?i)\b(?:page\s+)?(?:generated|rendered|executed|processed)\s+in\s+"
                   r"[\d.]+\s*(?:ms|milliseconds|s|sec|secs|seconds)"),
    ),
    (
        "visitor_counter",
        re.compile(r"(?i)\b(?:you\s+are\s+visitor|visitor\s+(?:number|count)|hits?\s*:)\s*[\d,]+"),
    ),
    (
        "cache_buster_url",
        re.compile(r"(?i)([?&](?:_|v|ts|cb|cachebuster|nocache|rnd|random)=)[A-Za-z0-9._-]{4,}"),
    ),
)

# Elements whose presence is chrome, advertising or scripting, never content.
DROP_TAGS: tuple[str, ...] = (
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "canvas",
    "iframe",
    "object",
    "embed",
    "link",
    "meta",
)

# Class/id substrings that mark a container as non-content. Matched
# case-insensitively against the whole attribute value, word-ish boundaries only,
# so "download" or "broadcast" cannot be swallowed by "ad".
VOLATILE_CONTAINER_RE = re.compile(
    r"(?i)(?:^|[\s_-])(?:ad|ads|advert|advertisement|adslot|ad-slot|banner-ad|carousel"
    r"|cookie-banner|cookie-notice|cookiebar|social-share|sharethis|addthis|skip-link"
    r"|csrf|antiforgery|session-timeout|livechat|chat-widget|recaptcha)(?:$|[\s_-])"
)

# Attributes that carry per-response noise.
VOLATILE_ATTRS: frozenset[str] = frozenset(
    {"nonce", "integrity", "data-nonce", "data-csrf", "data-request-id", "data-timestamp",
     "data-ts", "data-session", "data-session-id", "data-render-time", "crossorigin"}
)

_WS_RE = re.compile(r"[ \t   ]+")
_BLANKS_RE = re.compile(r"\n{3,}")


def _scrub_volatile_text(text: str) -> str:
    for name, pattern in VOLATILE_TEXT_PATTERNS:
        if name == "cache_buster_url":
            text = pattern.sub(r"\1<volatile>", text)
        else:
            text = pattern.sub(f"<volatile:{name}>", text)
    return text


def normalise_text(text: str) -> str:
    """Normalise free text (from HTML or PDF) for hashing and matching.

    Unicode is folded to NFC (never NFKC: that rewrites characters that can
    appear in names and amounts), line endings unified, trailing whitespace
    dropped, runs of blank lines collapsed, and volatile fragments replaced with
    stable placeholders.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("­", "")  # soft hyphen: PDF extraction artefact
    text = _scrub_volatile_text(text)
    lines = [_WS_RE.sub(" ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = _BLANKS_RE.sub("\n\n", text)
    return text.strip()


def _is_decomposed(tag) -> bool:
    # decompose() invalidates a tag's descendants, and find_all() hands back a
    # snapshot taken before the parent was removed.
    return bool(getattr(tag, "decomposed", False)) or tag.attrs is None


def _is_volatile_container(tag) -> bool:
    for attr in ("class", "id"):
        value = tag.get(attr)
        if not value:
            continue
        if isinstance(value, list):
            value = " ".join(value)
        if VOLATILE_CONTAINER_RE.search(str(value)):
            return True
    return False


def strip_volatile_html(html: str, *, base_url: str | None = None) -> BeautifulSoup:
    """Parse HTML and remove everything volatile, returning the soup."""
    soup = BeautifulSoup(html, "lxml")
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    for tag_name in DROP_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()
    for tag in soup.find_all(True):
        if _is_decomposed(tag):
            continue
        if _is_volatile_container(tag):
            tag.decompose()
    for tag in soup.find_all(True):
        if _is_decomposed(tag):
            continue
        for attr in list(tag.attrs):
            if attr.lower() in VOLATILE_ATTRS:
                del tag.attrs[attr]
        for attr in ("href", "src", "action"):
            value = tag.attrs.get(attr)
            if isinstance(value, str) and value.strip():
                tag.attrs[attr] = canonical_url(value) if "://" in value else value
    return soup


def html_to_text(html: str) -> str:
    """Extract normalised visible text from an HTML document."""
    soup = strip_volatile_html(html)
    text = soup.get_text("\n")
    return normalise_text(text)


def normalise_html_for_hash(html: str) -> str:
    """The canonical string form of a page, for change detection."""
    return html_to_text(html)
