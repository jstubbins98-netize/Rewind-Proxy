"""
Wayback Machine client — finds snapshots and fetches archived content.
"""

import logging
import re
import urllib.parse

import requests

import config

logger = logging.getLogger(__name__)

# Session reused across requests for connection pooling to archive.org
_session = requests.Session()
_session.headers.update({"User-Agent": config.FETCH_USER_AGENT})
_session.max_redirects = config.MAX_REDIRECTS


def _is_wayback_url(url: str) -> bool:
    """Return True if this is already a web.archive.org/web/... URL."""
    parsed = urllib.parse.urlparse(url)
    return parsed.netloc in ("web.archive.org", "www.archive.org") and parsed.path.startswith("/web/")


SNAPSHOT_PAGE_SIZE = 50


def find_snapshots(original_url: str, page: int = 0) -> tuple[list[dict], bool]:
    """List exact-URL captures, with a lookahead row for pagination.

    Raises on upstream failures rather than claiming there are no captures.
    Do not call this for assets or an already-selected Wayback replay URL.
    """
    response = _session.get(
        config.WAYBACK_CDX_URL,
        params={
            "url": original_url,
            "matchType": "exact",
            "output": "json",
            "filter": "statuscode:200",
            "fl": "timestamp,original",
            "collapse": "timestamp",
            "offset": str(page * SNAPSHOT_PAGE_SIZE),
            "limit": str(SNAPSHOT_PAGE_SIZE + 1),
        },
        timeout=config.REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    rows = response.json()
    if not isinstance(rows, list):
        raise ValueError("Wayback returned an invalid snapshot list")
    if not rows:
        return [], False
    if rows[0] != ["timestamp", "original"]:
        raise ValueError("Wayback returned unexpected snapshot columns")
    snapshots = []
    for row in rows[1:]:
        if not isinstance(row, list) or len(row) != 2:
            raise ValueError("Wayback returned an invalid snapshot row")
        timestamp, original = row
        if not isinstance(timestamp, str) or not re.fullmatch(r"\d{14}", timestamp):
            raise ValueError("Wayback returned an invalid capture date")
        if not isinstance(original, str) or not original.startswith(("http://", "https://")):
            raise ValueError("Wayback returned an invalid original URL")
        snapshots.append({
            "timestamp": timestamp,
            "original": original,
            "url": f"{config.WAYBACK_BASE}/web/{timestamp}/{original}",
        })
    return snapshots[:SNAPSHOT_PAGE_SIZE], len(snapshots) > SNAPSHOT_PAGE_SIZE


def resolve_to_wayback(original_url: str, preferred_timestamp: str = "") -> str:
    """
    Convert an original URL to its best Wayback Machine snapshot URL.
    If the URL is already a Wayback URL, return it unchanged (but normalised to https).
    """
    # Already a Wayback URL — normalise scheme to https for our fetch
    if _is_wayback_url(original_url):
        return original_url.replace("http://web.archive.org", "https://web.archive.org", 1)

    timestamp = preferred_timestamp or config.DEFAULT_WAYBACK_TIMESTAMP

    if timestamp:
        return f"{config.WAYBACK_BASE}/web/{timestamp}/{original_url}"

    # Use the CDX API to find the most recent 200-status snapshot
    try:
        params = {
            "url": original_url,
            "output": "json",
            "limit": "1",
            "filter": "statuscode:200",
            "fl": "timestamp,original",
            "fastLatest": "true",
        }
        resp = _session.get(
            config.WAYBACK_CDX_URL,
            params=params,
            timeout=10,
        )
        data = resp.json()
        # data[0] is the header row ["timestamp","original"], data[1] is first result
        if len(data) >= 2:
            ts, orig = data[1]
            logger.debug("CDX found snapshot %s for %s", ts, original_url)
            return f"{config.WAYBACK_BASE}/web/{ts}/{orig}"
    except Exception as exc:
        logger.warning("CDX lookup failed for %s: %s — using availability API", original_url, exc)

    # Fallback: availability API
    try:
        avail_url = f"{config.WAYBACK_BASE}/wayback/available?url={urllib.parse.quote(original_url)}"
        resp = _session.get(avail_url, timeout=10)
        data = resp.json()
        snapshot = data.get("archived_snapshots", {}).get("closest", {})
        if snapshot.get("available") and snapshot.get("url"):
            logger.debug("Availability API: %s", snapshot["url"])
            return snapshot["url"]
    except Exception as exc:
        logger.warning("Availability API failed for %s: %s", original_url, exc)

    # Last resort: let Wayback redirect us
    return f"{config.WAYBACK_BASE}/web/*/{original_url}"


def fetch(wayback_url: str, extra_headers: dict = None) -> requests.Response:
    """
    Fetch a URL from the Wayback Machine (or any https URL).
    Follows redirects, returns the final response.
    Raises requests.RequestException on network errors.
    """
    headers = {}
    if extra_headers:
        # Pass through safe request headers from the original client
        safe = {"accept", "accept-language", "referer"}
        for k, v in extra_headers.items():
            if k.lower() in safe:
                headers[k] = v

    # Always force https for archive.org
    fetch_url = wayback_url
    if fetch_url.startswith("http://web.archive.org"):
        fetch_url = "https" + fetch_url[4:]

    logger.info("Fetching: %s", fetch_url)
    response = _session.get(
        fetch_url,
        headers=headers,
        timeout=config.REQUEST_TIMEOUT,
        stream=True,
        allow_redirects=True,
    )
    return response


def extract_original_url_from_wayback(wayback_url: str) -> str:
    """
    Given https://web.archive.org/web/20040101120000/http://example.com/path
    return http://example.com/path
    """
    m = re.match(
        r"https?://web\.archive\.org/web/\d+[^/]*/(.+)$",
        wayback_url,
    )
    if m:
        return m.group(1)
    return wayback_url


def extract_timestamp_from_wayback(wayback_url: str) -> str:
    """Return the timestamp portion (e.g. '20040101120000') from a Wayback URL, or ''."""
    m = re.match(r"https?://web\.archive\.org/web/(\d+)[^/]*/", wayback_url)
    if m:
        return m.group(1)
    return ""
