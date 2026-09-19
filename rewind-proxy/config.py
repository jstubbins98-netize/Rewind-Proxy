"""
Rewind-Proxy configuration
"""

# Server settings
PROXY_HOST = "0.0.0.0"
PROXY_PORT = 8080

# Wayback Machine
WAYBACK_BASE = "https://web.archive.org"
WAYBACK_CDX_URL = "https://web.archive.org/cdx/search/cdx"

# HTTP client settings
REQUEST_TIMEOUT = 30
MAX_REDIRECTS = 10
MAX_CONTENT_SIZE = 10 * 1024 * 1024  # 10 MB

# Headers to strip from upstream responses (modern security headers that break old browsers)
STRIP_RESPONSE_HEADERS = {
    "content-security-policy",
    "content-security-policy-report-only",
    "x-frame-options",
    "x-xss-protection",
    "strict-transport-security",
    "feature-policy",
    "permissions-policy",
    "cross-origin-embedder-policy",
    "cross-origin-opener-policy",
    "cross-origin-resource-policy",
    "transfer-encoding",  # We rebuild this (body is already decompressed)
    "content-encoding",   # requests decompresses gzip; forwarding this header causes "cannot decode raw data"
    "connection",
    "keep-alive",
    "upgrade",
    "proxy-connection",
}

# Strip Wayback Machine toolbar/banner injected content
STRIP_WAYBACK_TOOLBAR = True

# User-Agent to send when fetching from Wayback Machine
FETCH_USER_AGENT = (
    "Mozilla/5.0 (compatible; Rewind-Proxy/1.0; "
    "+https://github.com/rewind-proxy)"
)

# Default Wayback timestamp to use when none specified in browser proxy mode.
# Using Jan 1 2000 as a sensible era for "retro browsing".
# The CDX / availability APIs are tried first; this only kicks in as a last resort.
DEFAULT_WAYBACK_TIMESTAMP = "20000101120000"

# Logging
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
