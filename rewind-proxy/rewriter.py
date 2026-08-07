"""
HTML / CSS / JavaScript rewriter for Rewind-Proxy.

Rewrites all URLs in an archived Wayback Machine page so that they are
fetched through the proxy rather than directly.  Also strips Wayback's own
injected toolbar/scripts and simplifies the page for older browsers.
"""

import logging
import re
import urllib.parse

from bs4 import BeautifulSoup, Comment

logger = logging.getLogger(__name__)

# Wayback Machine inserts a toolbar inside a specific id; also look for the
# characteristic script comment/block it injects.
_WAYBACK_TOOLBAR_IDS = {"wm-ipp-base", "wm-ipp", "donato", "playback"}
_WAYBACK_SCRIPT_RE = re.compile(
    r"(window\.RufflePlayer|__wm\.|wm\.init|wayback_machine|wombat\.js|"
    r"analytics\.archive\.org|_sf_async_config|__gaTracker)",
    re.IGNORECASE,
)

# CSS url() pattern
_CSS_URL_RE = re.compile(r"""url\(\s*['"]?([^'"\)]+)['"]?\s*\)""")


def _extract_ts(wayback_url: str) -> str:
    """Return the timestamp portion of a Wayback URL (e.g. '20001231120000'), or ''."""
    m = re.match(r"https?://web\.archive\.org/web/(\d+)[^/]*/", wayback_url)
    return m.group(1) if m else ""


def _make_proxy_url(
    href: str,
    base_url: str,
    page_wayback_url: str,
    web_proxy_mode: bool = False,
) -> str:
    """
    Turn any href/src/action into a URL routed through the proxy.

    web_proxy_mode=False (standard proxy mode — browser configured with proxy settings):
      All URLs become http://web.archive.org/web/... which the browser sends back
      to us via its proxy configuration.

    web_proxy_mode=True (direct mode — browser accesses our server directly):
      All URLs become /r?url=<encoded_wayback_url> so the browser never leaves
      our server and archive.org is never contacted directly.
    """
    href = href.strip()

    if not href or href.startswith(("javascript:", "data:", "mailto:", "#", "about:")):
        return href

    # ── Resolve to an intermediate "standard proxy mode" URL ──────────
    if href.startswith("https://web.archive.org/web/"):
        result = "http://web.archive.org" + href[len("https://web.archive.org"):]
    elif href.startswith("http://web.archive.org/web/"):
        result = href
    elif re.match(r"^/web/\d", href):
        result = "http://web.archive.org" + href
    elif href.startswith("http://") or href.startswith("https://"):
        result = href  # proxy will wrap in Wayback on next request
    else:
        resolved = urllib.parse.urljoin(base_url, href)
        if resolved.startswith("https://web.archive.org/web/"):
            result = "http://web.archive.org" + resolved[len("https://web.archive.org"):]
        else:
            result = resolved

    if not web_proxy_mode:
        return result

    # ── web_proxy_mode: convert to /r?url=<encoded_wayback_url> ──────
    if "web.archive.org/web/" in result:
        # Normalise to https for archive.org
        wayback = result.replace("http://web.archive.org/", "https://web.archive.org/", 1)
    else:
        # Non-Wayback URL — wrap it using the current page's timestamp
        ts = _extract_ts(page_wayback_url) or "*"
        wayback = f"https://web.archive.org/web/{ts}/{result}"

    return f"/r?url={urllib.parse.quote(wayback, safe='')}"


def _rewrite_css_urls(
    css_text: str,
    base_url: str,
    page_wayback_url: str,
    web_proxy_mode: bool = False,
) -> str:
    """Rewrite url() references inside a CSS string."""
    def replacer(m):
        original = m.group(1)
        new_url = _make_proxy_url(original, base_url, page_wayback_url, web_proxy_mode)
        return f"url('{new_url}')"
    return _CSS_URL_RE.sub(replacer, css_text)


def rewrite_html(
    html_bytes: bytes,
    content_type: str,
    page_wayback_url: str,
    base_url: str,
    web_proxy_mode: bool = False,
) -> bytes:
    """
    Parse *html_bytes*, strip Wayback toolbar, rewrite all URLs, and return
    the modified HTML as bytes.

    *page_wayback_url*: the full https://web.archive.org/web/... URL we fetched.
    *base_url*: the original site URL (e.g. http://example.com/path/) used for
                resolving relative URLs.
    *web_proxy_mode*: when True, rewrite all links to /r?url=... so the browser
                      never leaves our server (used for direct-access mode).
    """
    # Detect charset from Content-Type or <meta> before parsing
    charset = "utf-8"
    ct_lower = content_type.lower()
    m = re.search(r"charset=([^\s;]+)", ct_lower)
    if m:
        charset = m.group(1).strip()

    # Decode carefully — replace undecodable bytes
    try:
        html_str = html_bytes.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        html_str = html_bytes.decode("utf-8", errors="replace")

    soup = BeautifulSoup(html_str, "html.parser")

    # ------------------------------------------------------------------
    # 1. Strip Wayback toolbar elements
    # ------------------------------------------------------------------
    for wm_id in _WAYBACK_TOOLBAR_IDS:
        el = soup.find(id=wm_id)
        if el:
            el.decompose()

    # Remove all <script> tags that reference Wayback infrastructure
    for script in soup.find_all("script"):
        src = script.get("src", "")
        content = script.string or ""
        if (
            "web-static.archive.org" in src
            or "web.archive.org" in src
            or "archive.org" in src
            or _WAYBACK_SCRIPT_RE.search(src)
            or _WAYBACK_SCRIPT_RE.search(content)
        ):
            script.decompose()

    # Remove Wayback's injected <link> stylesheets (banner-styles.css,
    # iconochive.css, etc.) hosted on web-static.archive.org.
    # These are Wayback's own toolbar CSS — not the archived page's styles.
    for link in soup.find_all("link"):
        href = link.get("href", "")
        if (
            "web-static.archive.org" in href
            or "banner-styles.css" in href
            or "iconochive.css" in href
        ):
            link.decompose()

    # Remove Wayback HTML comments that start the injected block
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        if "archive.org" in comment or "wayback" in comment.lower():
            comment.extract()

    # ------------------------------------------------------------------
    # 2. Handle <base href="...">
    # ------------------------------------------------------------------
    base_tag = soup.find("base")
    if base_tag and base_tag.get("href"):
        raw_base = base_tag["href"]
        new_base = _make_proxy_url(raw_base, base_url, page_wayback_url, web_proxy_mode)
        base_tag["href"] = new_base
        # Update our base_url for subsequent relative resolution
        base_url = urllib.parse.urljoin(base_url, raw_base)

    # ------------------------------------------------------------------
    # 3. Rewrite link attributes
    # ------------------------------------------------------------------
    ATTR_MAP = {
        "a":          ["href"],
        "area":       ["href"],
        "link":       ["href"],
        "img":        ["src", "longdesc", "usemap"],
        "iframe":     ["src"],
        "frame":      ["src"],
        "embed":      ["src"],
        "object":     ["data"],
        "source":     ["src", "srcset"],
        "video":      ["src", "poster"],
        "audio":      ["src"],
        "form":       ["action"],
        "input":      ["src"],
        "blockquote": ["cite"],
        "q":          ["cite"],
        "ins":        ["cite"],
        "del":        ["cite"],
        "script":     ["src"],
    }

    for tag_name, attrs in ATTR_MAP.items():
        for tag in soup.find_all(tag_name):
            for attr in attrs:
                val = tag.get(attr)
                if val:
                    if attr == "srcset":
                        parts = []
                        for part in val.split(","):
                            bits = part.strip().split()
                            if bits:
                                bits[0] = _make_proxy_url(
                                    bits[0], base_url, page_wayback_url, web_proxy_mode
                                )
                            parts.append(" ".join(bits))
                        tag[attr] = ", ".join(parts)
                    else:
                        tag[attr] = _make_proxy_url(
                            val, base_url, page_wayback_url, web_proxy_mode
                        )

    # ------------------------------------------------------------------
    # 4. Rewrite inline style url() and style attributes
    # ------------------------------------------------------------------
    for tag in soup.find_all(style=True):
        tag["style"] = _rewrite_css_urls(
            tag["style"], base_url, page_wayback_url, web_proxy_mode
        )

    for style_tag in soup.find_all("style"):
        if style_tag.string:
            style_tag.string = _rewrite_css_urls(
                style_tag.string, base_url, page_wayback_url, web_proxy_mode
            )

    # ------------------------------------------------------------------
    # 5. Add a small Rewind-Proxy info bar at the top of <body>
    # ------------------------------------------------------------------
    body = soup.find("body")
    if body:
        from wayback import extract_original_url_from_wayback, extract_timestamp_from_wayback
        orig = extract_original_url_from_wayback(page_wayback_url)
        ts = extract_timestamp_from_wayback(page_wayback_url)
        date_str = ""
        if ts and len(ts) >= 8:
            date_str = f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}"

        if web_proxy_mode:
            browse_url  = f"/r?url={urllib.parse.quote(f'https://web.archive.org/web/*/{orig}', safe='')}"
            history_url = f"/r?url={urllib.parse.quote(f'https://web.archive.org/web/19960101000000*/{orig}', safe='')}"
        else:
            browse_url  = f"http://web.archive.org/web/*/{orig}"
            history_url = f"http://web.archive.org/web/19960101000000*/{orig}"

        bar_html = (
            f'<table width="100%" border="1" cellpadding="3" cellspacing="0" '
            f'bgcolor="#FFFFE0"><tr><td>'
            f'<b>Rewind-Proxy</b> &mdash; Archived: <b>{date_str}</b> &mdash; '
            f'Original: <a href="{browse_url}">{orig}</a> &mdash; '
            f'<a href="{history_url}">Browse history</a> &mdash; '
            f'<a href="/">Home</a>'
            f'</td></tr></table>'
        )
        bar = BeautifulSoup(bar_html, "html.parser")
        body.insert(0, bar)

    result = str(soup)
    return result.encode("utf-8", errors="replace")


def rewrite_css(
    css_bytes: bytes,
    content_type: str,
    base_url: str,
    page_wayback_url: str,
    web_proxy_mode: bool = False,
) -> bytes:
    """Rewrite url() references in a standalone CSS file."""
    charset = "utf-8"
    m = re.search(r"charset=([^\s;]+)", content_type.lower())
    if m:
        charset = m.group(1).strip()
    try:
        css_str = css_bytes.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        css_str = css_bytes.decode("utf-8", errors="replace")

    result = _rewrite_css_urls(css_str, base_url, page_wayback_url, web_proxy_mode)
    return result.encode("utf-8", errors="replace")
