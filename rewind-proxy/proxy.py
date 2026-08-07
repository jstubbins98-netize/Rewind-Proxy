"""
Rewind-Proxy — core HTTP proxy request handler.

Handles standard HTTP proxy requests (GET http://example.com/ HTTP/1.0)
and CONNECT tunnelling stubs.  All traffic is routed through the Internet
Archive Wayback Machine so that old browsers can browse archived content.
"""

import logging
import os
import re
import socket
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

import requests

import config
import pi_setup
from wayback import resolve_to_wayback, fetch, extract_original_url_from_wayback
from rewriter import rewrite_html, rewrite_css

logger = logging.getLogger(__name__)


def _build_pi_section() -> str:
    """
    Return an HTML string for the Raspberry Pi 5 ethernet wizard section.
    Returns an empty string when not running on a Pi 5.
    """
    st = pi_setup.get_status()
    status = st["status"]

    if status == pi_setup.S_NOT_PI:
        return ""   # Not a Pi — hide this section entirely

    iface      = st.get("eth_iface") or "eth0"
    eth_ip     = st.get("eth_ip") or pi_setup.ETH_IP
    port       = st.get("proxy_port", 8080)
    old_ip     = st.get("old_computer_ip")
    is_root    = st.get("is_root", False)
    dnsmasq    = st.get("dnsmasq_running", False)
    manual     = st.get("manual_cmds", [])
    error_msg  = st.get("error", "")

    # ── Step indicators ────────────────────────────────────────────────
    step = 1
    if status in (pi_setup.S_CONFIGURING, pi_setup.S_WAITING_DEVICE):
        step = 2
    elif status == pi_setup.S_CONNECTED:
        step = 3

    step_style = ['', '', '']   # 0-indexed, steps 1–3
    for i in range(3):
        step_style[i] = (
            'bgcolor="#FFFF88"' if (i + 1) == step
            else ('bgcolor="#DDFFDD"' if (i + 1) < step else '')
        )

    steps_html = f"""
<table border="1" cellpadding="6" cellspacing="0" width="100%">
<tr {step_style[0]}><td width="30"><b>1</b></td>
  <td>Plug the ethernet cable from your old computer into the Pi&nbsp;5's ethernet port.</td></tr>
<tr {step_style[1]}><td><b>2</b></td>
  <td>The Pi configures the port and waits for your old computer to appear.</td></tr>
<tr {step_style[2]}><td><b>3</b></td>
  <td>Configure your old computer's browser proxy settings &mdash;
      the Pi will fetch all pages from the Wayback Machine on its behalf.</td></tr>
</table>
"""

    # ── Status-specific body ───────────────────────────────────────────
    if status == pi_setup.S_DETECTING:
        body = "<p>Detecting hardware&hellip;</p>"

    elif status == pi_setup.S_WAITING_CABLE:
        body = f"""
<p><b>&#9654; Step 1: Connect the ethernet cable.</b></p>
<p>Take a standard ethernet cable and plug one end into your old computer
and the other into the Pi&nbsp;5's ethernet port
(<tt>{iface}</tt>).  This page refreshes automatically once the cable
is detected.</p>
<p><i>Waiting for cable on <tt>{iface}</tt>&hellip;</i></p>
<p><small>
  <b>Note:</b> if you do not have a crossover cable, a regular straight-through
  cable works fine &mdash; the Pi&nbsp;5 auto-MDI/MDI-X negotiates automatically.
</small></p>
"""

    elif status == pi_setup.S_CONFIGURING:
        body = "<p>Cable detected &mdash; configuring ethernet interface&hellip;</p>"

    elif status == pi_setup.S_WAITING_DEVICE:
        if is_root:
            dhcp_note = (
                f"<p>DHCP is <b>active</b> (dnsmasq) &mdash; your old computer "
                f"should receive an IP automatically in the range "
                f"<tt>{pi_setup.DHCP_RANGE_START}</tt>&ndash;"
                f"<tt>{pi_setup.DHCP_RANGE_END}</tt>.</p>"
                if dnsmasq else
                f"<p>DHCP is not available. Set a <b>static IP</b> on your old computer:</p>"
                f"<table border='1' cellpadding='4'>"
                f"<tr><td>IP address</td><td><tt>{pi_setup.STATIC_OLD_IP}</tt></td></tr>"
                f"<tr><td>Subnet mask</td><td><tt>{pi_setup.ETH_NETMASK}</tt></td></tr>"
                f"<tr><td>Gateway</td><td><tt>{pi_setup.STATIC_GW}</tt></td></tr>"
                f"<tr><td>DNS</td><td><tt>{pi_setup.STATIC_DNS}</tt></td></tr>"
                f"</table>"
            )
            body = f"""
<p><b>&#9654; Step 2: The Pi is ready.  Now set up your old computer.</b></p>
<p>The Pi&nbsp;5 ethernet port (<tt>{iface}</tt>) is configured as
<tt>{eth_ip}</tt>. {dhcp_note}</p>
<p><i>Scanning for your old computer&hellip;</i></p>
"""
        else:
            # Not root — show manual setup commands
            cmd_list = "".join(f"<li><tt>{c}</tt></li>" for c in manual)
            body = f"""
<p><b>&#9654; Step 2: Run the following commands on the Pi to configure the ethernet port.</b></p>
<p>Rewind-Proxy is not running as root, so the network must be set up manually.
Open a terminal on the Pi and run:</p>
<ol>{cmd_list}</ol>
<p>Then set a <b>static IP</b> on your old computer:</p>
<table border="1" cellpadding="4">
<tr><td>IP address</td><td><tt>{pi_setup.STATIC_OLD_IP}</tt></td></tr>
<tr><td>Subnet mask</td><td><tt>{pi_setup.ETH_NETMASK}</tt></td></tr>
<tr><td>Gateway</td><td><tt>{pi_setup.STATIC_GW}</tt></td></tr>
<tr><td>DNS</td><td><tt>{pi_setup.STATIC_DNS}</tt></td></tr>
</table>
<p><i>Waiting for old computer to appear&hellip;</i></p>
"""

    elif status == pi_setup.S_CONNECTED:
        body = f"""
<p><b>&#10003; Step 3: Old computer connected!</b></p>
<p>A device was found at <tt><b>{old_ip}</b></tt> on the ethernet link.</p>
<p>On your old computer, open the browser's proxy / network settings and enter:</p>
<table border="2" cellpadding="6" cellspacing="0" bgcolor="#DDFFDD">
<tr><td><b>HTTP Proxy host</b></td><td><tt><font size="+1">{eth_ip}</font></tt></td></tr>
<tr><td><b>Port</b></td><td><tt><font size="+1">{port}</font></tt></td></tr>
</table>
<p>Then browse to any <tt>http://</tt> address &mdash; the Pi will fetch
the Wayback Machine archive automatically.</p>
<p>You can also open the Rewind-Proxy home page directly on the old computer:<br>
<tt>http://{eth_ip}:{port}/</tt></p>
"""

    elif status == pi_setup.S_ERROR:
        body = f"<p><b>Error:</b> {error_msg}</p>"

    else:
        body = f"<p>Status: {status}</p>"

    # ── Auto-refresh while waiting ─────────────────────────────────────
    refresh_meta = ""
    if status in (pi_setup.S_WAITING_CABLE, pi_setup.S_CONFIGURING,
                  pi_setup.S_WAITING_DEVICE, pi_setup.S_DETECTING):
        refresh_meta = '<meta http-equiv="refresh" content="4">'

    return f"""
<hr>
<h2>Raspberry Pi 5 &mdash; Old Computer Connection Wizard</h2>
{refresh_meta}
{steps_html}
{body}
"""


def _month_options(selected: int = 1) -> str:
    months = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]
    opts = []
    for i, name in enumerate(months, 1):
        sel = ' selected' if i == selected else ''
        opts.append(f'<option value="{i:02d}"{sel}>{name}</option>')
    return "\n".join(opts)


def _day_options(selected: int = 1) -> str:
    opts = []
    for d in range(1, 32):
        sel = ' selected' if d == selected else ''
        opts.append(f'<option value="{d:02d}"{sel}>{d}</option>')
    return "\n".join(opts)


def _build_home_page() -> bytes:
    """Build the home page HTML using runtime-resolved URLs from env vars."""
    import datetime
    public_home  = os.environ.get("REWIND_PUBLIC_HOME", "http://localhost:8080/")
    proxy_host   = os.environ.get("REWIND_PROXY_HOST", "localhost")
    proxy_port   = os.environ.get("REWIND_PROXY_PORT", "8080")
    network_note = os.environ.get("REWIND_NETWORK_NOTE", "")

    # Default date: 1 Jan 2000 (a good "time travel" starting point)
    default_day   = 1
    default_month = 1
    default_year  = 2000

    month_opts = _month_options(default_month)
    day_opts   = _day_options(default_day)

    pi_section = _build_pi_section()

    html = f"""<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">
<html>
<head><title>Rewind-Proxy</title></head>
<body bgcolor="#FFFFFF">
<h1>Rewind-Proxy</h1>
<p>Browse the archived web through the
<a href="http://web.archive.org/">Internet Archive Wayback Machine</a>
using any browser &mdash; including old computers from the 1990s and 2000s.</p>
<hr>
<table width="100%" border="2" cellpadding="6" cellspacing="0" bgcolor="#E8F4FF">
<tr><td>
<h2>Your Rewind-Proxy address</h2>
<p><b>Open this URL in any browser:</b><br>
<font size="+1"><tt>{public_home}</tt></font></p>
<p><b>-- OR -- configure your old browser's proxy settings:</b><br>
<table border="1" cellpadding="4" cellspacing="0">
<tr><td><b>HTTP Proxy host</b></td><td><tt>{proxy_host}</tt></td></tr>
<tr><td><b>Port</b></td><td><tt>{proxy_port}</tt></td></tr>
</table>
Then browse any <tt>http://</tt> URL normally &mdash; the proxy fetches
the archived version automatically.</p>
<p><small>{network_note}</small></p>
</td></tr>
</table>
{pi_section}
<hr>
<h2>Browse a URL at a specific date</h2>
<form method="GET" action="/go">
<table border="0" cellpadding="4" cellspacing="2">
<tr>
  <td><b>URL:</b></td>
  <td><input type="text" name="url" size="50" value="http://www."></td>
</tr>
<tr>
  <td><b>Date:</b></td>
  <td>
    Day:&nbsp;<select name="day">
{day_opts}
    </select>
    &nbsp;Month:&nbsp;<select name="month">
{month_opts}
    </select>
    &nbsp;Year:&nbsp;<input type="text" name="year" size="5" value="{default_year}">
    &nbsp;<small>(1996&ndash;present)</small>
  </td>
</tr>
<tr>
  <td></td>
  <td><input type="submit" value="Go to that date"></td>
</tr>
</table>
<p><small>Leave the date fields as-is to get the nearest archived snapshot
to that date. The Wayback Machine has archives going back to 1996.</small></p>
</form>
<hr>
<h2>Quick links <small>(nearest to 1 Jan 2000)</small></h2>
<ul>
  <li><a href="/go?url=http://www.yahoo.com/&amp;day=01&amp;month=01&amp;year=2000">Yahoo!</a></li>
  <li><a href="/go?url=http://www.google.com/&amp;day=01&amp;month=01&amp;year=2000">Google</a></li>
  <li><a href="/go?url=http://www.bbc.co.uk/&amp;day=01&amp;month=01&amp;year=2000">BBC News</a></li>
  <li><a href="/go?url=http://www.cnn.com/&amp;day=01&amp;month=01&amp;year=2000">CNN</a></li>
  <li><a href="/go?url=http://www.wikipedia.org/&amp;day=01&amp;month=01&amp;year=2003">Wikipedia</a></li>
  <li><a href="/go?url=http://www.geocities.com/&amp;day=01&amp;month=01&amp;year=1999">GeoCities</a></li>
  <li><a href="/go?url=http://www.altavista.com/&amp;day=01&amp;month=01&amp;year=1999">AltaVista</a></li>
  <li><a href="/go?url=http://www.askjeeves.com/&amp;day=01&amp;month=01&amp;year=2000">Ask Jeeves</a></li>
</ul>
<hr>
<h2>Help</h2>
<ul>
  <li><a href="/setup">&#x1F4BB; How to use this on a real old computer via Raspberry Pi 5</a></li>
</ul>
<hr>
<p><small>Rewind-Proxy &mdash; powered by the Internet Archive</small></p>
</body>
</html>
"""
    return html.encode("utf-8")

ERROR_TEMPLATE = """\
<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">
<html><head><title>Rewind-Proxy Error</title></head>
<body bgcolor="#FFFFFF">
<h1>Rewind-Proxy Error</h1>
<p><b>{code}: {reason}</b></p>
<p>{detail}</p>
<p><a href="/">Back to home</a></p>
</body></html>
"""


def _build_setup_page() -> bytes:
    """Return the HTML setup/instructions page for Pi 5 + old computer usage."""
    proxy_host = os.environ.get("REWIND_PROXY_HOST", "192.168.100.1")
    proxy_port = os.environ.get("REWIND_PROXY_PORT", "8080")

    pi_ip   = pi_setup.ETH_IP          # 192.168.100.1
    old_ip  = pi_setup.STATIC_OLD_IP   # 192.168.100.2
    gw      = pi_setup.STATIC_GW
    dns     = pi_setup.STATIC_DNS
    netmask = pi_setup.ETH_NETMASK

    html = f"""<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">
<html>
<head><title>Rewind-Proxy &mdash; Setup Guide</title></head>
<body bgcolor="#FFFFFF">
<h1>Rewind-Proxy &mdash; Setup Guide</h1>
<p>This guide explains how to browse archived websites from the 1990s&ndash;2010s
on a <b>real old computer</b> using a <b>Raspberry Pi 5</b> as the go-between.</p>

<hr>
<h2>What you need</h2>
<ul>
  <li>Raspberry Pi 5 (already running Rewind-Proxy &mdash; that&#39;s what you&#39;re reading now)</li>
  <li>An ethernet cable</li>
  <li>The old computer you want to browse from</li>
  <li>A modern computer or phone to control the Pi (optional but helpful)</li>
</ul>

<hr>
<h2>Step 1 &mdash; Connect the old computer to the Pi</h2>
<p>Plug one end of the ethernet cable into the <b>old computer</b> and the other end
into the <b>Pi&rsquo;s ethernet port</b>.</p>
<p>The Pi will automatically share a private network over that cable.
If the Pi&rsquo;s home page (this proxy) shows a green &ldquo;Old computer connected&rdquo;
banner, the link is already up.</p>

<hr>
<h2>Step 2 &mdash; Give the old computer a network address</h2>
<p>If the Pi is running dnsmasq (it tries to start it automatically when run as root),
the old computer will get an IP address automatically via DHCP &mdash; skip to Step 3.</p>
<p>If <b>not</b>, set the old computer&rsquo;s network settings manually:</p>
<table border="1" cellpadding="4" cellspacing="0">
<tr><th align="left">Setting</th><th align="left">Value</th></tr>
<tr><td>IP address</td><td><tt>{old_ip}</tt></td></tr>
<tr><td>Subnet mask</td><td><tt>{netmask}</tt></td></tr>
<tr><td>Default gateway</td><td><tt>{gw}</tt></td></tr>
<tr><td>DNS server</td><td><tt>{dns}</tt></td></tr>
</table>
<p><small>On Windows 95/98/XP: Control Panel &rarr; Network &rarr; TCP/IP &rarr; Properties.<br>
On Mac OS 9: Apple menu &rarr; Control Panels &rarr; TCP/IP. Set &ldquo;Connect via&rdquo;
to Ethernet and &ldquo;Configure&rdquo; to Manually.</small></p>

<hr>
<h2>Step 3 &mdash; Point the old browser at the proxy</h2>
<p>Open the old browser and go to its proxy settings.
Enter <b>the Pi&rsquo;s IP address</b> as the HTTP proxy:</p>
<table border="1" cellpadding="4" cellspacing="0">
<tr><th align="left">Setting</th><th align="left">Value</th></tr>
<tr><td>HTTP proxy host</td><td><tt>{pi_ip}</tt></td></tr>
<tr><td>Port</td><td><tt>{proxy_port}</tt></td></tr>
</table>
<p><small><b>Netscape Navigator 4:</b> Edit &rarr; Preferences &rarr; Advanced &rarr; Proxies
&rarr; Manual proxy configuration. Enter the host and port above for &ldquo;HTTP Proxy&rdquo;.<br>
<b>Internet Explorer 5/6:</b> Tools &rarr; Internet Options &rarr; Connections
&rarr; LAN Settings &rarr; check &ldquo;Use a proxy server&rdquo;, enter host and port.<br>
<b>Mac IE / iCab:</b> Edit &rarr; Preferences &rarr; Network &rarr; Proxies.
</small></p>

<hr>
<h2>Step 4 &mdash; Browse!</h2>
<p>With the proxy configured, type any website address in the old browser&rsquo;s
location bar and press Enter. Rewind-Proxy will fetch the nearest archived snapshot
from the <a href="/r?url=https%3A%2F%2Fweb.archive.org%2F">Internet Archive Wayback Machine</a>
and serve it over plain HTTP so old browsers can read it.</p>
<p>You can also open the Rewind-Proxy home page directly on the old computer:</p>
<p>&nbsp;&nbsp;&nbsp;<tt>http://{pi_ip}:{proxy_port}/</tt></p>
<p>From there you can pick a specific date and use the quick links.</p>

<hr>
<h2>Troubleshooting</h2>
<dl>
<dt><b>Old browser says &ldquo;Unable to connect&rdquo; / &ldquo;Connection refused&rdquo;</b></dt>
<dd>Check the ethernet cable is plugged in at both ends. Confirm the old computer
has the IP address from Step 2. Verify the proxy host/port in the browser
matches <tt>{pi_ip}:{proxy_port}</tt>.</dd>
<dt><b>Pages load but images are missing</b></dt>
<dd>Some images were never archived. This is normal &mdash; the Wayback Machine
only has what it crawled at the time.</dd>
<dt><b>Page says &ldquo;SSL&rdquo; or certificate errors</b></dt>
<dd>Make sure the browser is configured to use the proxy for HTTP (not HTTPS).
All HTTPS is handled by Rewind-Proxy; the old browser never needs to negotiate TLS.</dd>
<dt><b>Pi home page shows &ldquo;Not running on a Pi&rdquo;</b></dt>
<dd>Rewind-Proxy is running on a non-Pi machine (a laptop or cloud server).
The ethernet wizard is disabled, but you can still use the proxy by connecting
the old computer to the same network and pointing its browser at this machine&rsquo;s
IP address on port <tt>{proxy_port}</tt>.</dd>
</dl>

<hr>
<p><a href="/">&#8592; Back to Rewind-Proxy home</a></p>
<p><small>Rewind-Proxy &mdash; powered by the Internet Archive</small></p>
</body>
</html>
"""
    return html.encode("utf-8")


def _error_page(code: int, reason: str, detail: str = "") -> bytes:
    return ERROR_TEMPLATE.format(code=code, reason=reason, detail=detail).encode("utf-8")


class RewindProxyHandler(BaseHTTPRequestHandler):
    """Handle a single HTTP proxy (or direct) request."""

    # Use HTTP/1.0 responses so very old clients understand them
    protocol_version = "HTTP/1.0"
    server_version = "Rewind-Proxy/1.0"

    # Suppress default BaseHTTPRequestHandler logging (we do our own)
    def log_message(self, fmt, *args):
        logger.info("CLIENT %s - %s", self.address_string(), fmt % args)

    def log_error(self, fmt, *args):
        logger.warning("CLIENT %s - %s", self.address_string(), fmt % args)

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------

    def do_GET(self):
        self._handle_request("GET")

    def do_POST(self):
        self._handle_request("POST")

    def do_HEAD(self):
        self._handle_request("HEAD")

    def do_CONNECT(self):
        """
        CONNECT is used for HTTPS tunnelling.  Since we serve everything
        as plain HTTP through the Wayback Machine, we tell the client we
        don't support tunnelling and suggest they use plain HTTP URLs.
        """
        self.send_error(
            501,
            "CONNECT not supported — please use http:// URLs. "
            "Rewind-Proxy will fetch the archived version automatically.",
        )

    # ------------------------------------------------------------------
    # Request routing
    # ------------------------------------------------------------------

    def _handle_request(self, method: str):
        path = self.path

        # Direct requests to the proxy's own interface
        if not path.startswith("http://") and not path.startswith("https://"):
            self._handle_direct(method, path)
            return

        # Standard proxy request: GET http://example.com/... HTTP/1.0
        self._handle_proxy(method, path)

    def _handle_direct(self, method: str, path: str):
        """Handle a request addressed directly to the proxy (not a proxy request)."""
        # Root → home page
        if path in ("/", ""):
            self._send_response(200, "OK", b"text/html", _build_home_page())
            return

        # /go?url=...&day=DD&month=MM&year=YYYY — URL navigation form
        if path.startswith("/go"):
            parsed = urllib.parse.urlparse(path)
            params = urllib.parse.parse_qs(parsed.query)
            url = params.get("url", [""])[0].strip()
            if not url:
                self._send_response(400, "Bad Request", b"text/html",
                                    _error_page(400, "Bad Request", "No URL provided."))
                return
            if not url.startswith(("http://", "https://")):
                url = "http://" + url

            # Build a Wayback timestamp from the date controls if present
            timestamp = ""
            day_str   = params.get("day",   [""])[0].strip()
            month_str = params.get("month", [""])[0].strip()
            year_str  = params.get("year",  [""])[0].strip()
            if year_str:
                try:
                    year  = max(1996, min(2099, int(year_str)))
                    month = max(1,    min(12,   int(month_str))) if month_str else 1
                    day   = max(1,    min(31,   int(day_str)))   if day_str   else 1
                    timestamp = f"{year:04d}{month:02d}{day:02d}120000"
                except ValueError:
                    pass  # bad input — fall through to "most recent"

            # Resolve to the Wayback URL for that date, then serve directly.
            # We do NOT redirect — Replit's reverse proxy can mangle relative
            # Location headers, sending the browser to an unreachable localhost URL.
            wayback_url = resolve_to_wayback(url, preferred_timestamp=timestamp)
            self._serve_wayback_url(wayback_url)
            return

        # /r?url=... — serve any Wayback URL directly through our proxy
        if path.startswith("/r"):
            self._handle_resource_proxy(path)
            return

        # /setup — human-readable setup / instructions page
        if path.startswith("/setup"):
            self._send_response(200, "OK", b"text/html", _build_setup_page())
            return

        # Anything else: 404
        self._send_response(
            404, "Not Found", b"text/html",
            _error_page(404, "Not Found", f"Path '{path}' not found on this proxy."),
        )

    def _handle_proxy(self, method: str, url: str):
        """Proxy a request through the Wayback Machine."""
        # ── Route /r and /go paths back to our own handlers ───────────────
        # When the browser is configured with proxy settings, clicking a
        # /r?url=... or /go?url=... link resolves it relative to the current
        # page URL (e.g. http://apple.com/r?url=...).  The browser sends that
        # full URL to us as a proxy request; we strip the host and route it.
        _pu = urllib.parse.urlparse(url)
        if (_pu.path.startswith("/r") or _pu.path.startswith("/go")
                or _pu.path.startswith("/setup")):
            # Browser proxy mode: clicking a /r?url=..., /go?url=..., or /setup
            # link resolves it relative to the current page host, so the request
            # arrives as e.g. GET http://apple.com/r?url=... — strip the host
            # and route it to our own direct handler.
            direct_path = _pu.path + ("?" + _pu.query if _pu.query else "")
            self._handle_direct(method, direct_path)
            return

        # Read request body for POST
        body = b""
        length_str = self.headers.get("Content-Length")
        if length_str:
            try:
                body = self.rfile.read(int(length_str))
            except Exception:
                pass

        # Resolve the URL to a Wayback Machine snapshot
        try:
            wayback_url = resolve_to_wayback(url)
        except Exception as exc:
            logger.exception("Failed to resolve %s", url)
            self._send_response(
                502, "Bad Gateway", b"text/html",
                _error_page(502, "Bad Gateway", f"Could not resolve Wayback URL: {exc}"),
            )
            return

        # Fetch from Wayback Machine
        try:
            resp = fetch(wayback_url, extra_headers=dict(self.headers))
        except requests.exceptions.Timeout:
            self._send_response(
                504, "Gateway Timeout", b"text/html",
                _error_page(504, "Gateway Timeout", f"Timed out fetching {wayback_url}"),
            )
            return
        except requests.exceptions.ConnectionError as exc:
            self._send_response(
                502, "Bad Gateway", b"text/html",
                _error_page(502, "Bad Gateway", f"Connection error: {exc}"),
            )
            return
        except Exception as exc:
            logger.exception("Unexpected error fetching %s", wayback_url)
            self._send_response(
                502, "Bad Gateway", b"text/html",
                _error_page(502, "Bad Gateway", f"Unexpected error: {exc}"),
            )
            return

        # Read response body (limited size)
        try:
            raw_body = resp.content
            if len(raw_body) > config.MAX_CONTENT_SIZE:
                raw_body = raw_body[: config.MAX_CONTENT_SIZE]
        except Exception as exc:
            self._send_response(
                502, "Bad Gateway", b"text/html",
                _error_page(502, "Bad Gateway", f"Error reading response body: {exc}"),
            )
            return

        content_type = resp.headers.get("Content-Type", "text/html")
        ct_lower = content_type.lower()

        # The final URL after redirects (Wayback may have redirected to a different timestamp)
        final_wayback_url = resp.url
        original_url = extract_original_url_from_wayback(final_wayback_url)
        if not original_url or original_url == final_wayback_url:
            original_url = url

        # Rewrite HTML responses
        # Use web_proxy_mode=True so links become /r?url=... in both proxy
        # mode and direct mode — the address bar never shows archive.org URLs.
        if "text/html" in ct_lower or "application/xhtml" in ct_lower:
            try:
                body_out = rewrite_html(
                    raw_body,
                    content_type,
                    page_wayback_url=final_wayback_url,
                    base_url=original_url,
                    web_proxy_mode=True,
                )
                content_type = "text/html; charset=utf-8"
            except Exception as exc:
                logger.warning("HTML rewrite failed for %s: %s", final_wayback_url, exc)
                body_out = raw_body

        # Rewrite CSS responses
        elif "text/css" in ct_lower:
            try:
                body_out = rewrite_css(
                    raw_body,
                    content_type,
                    base_url=original_url,
                    page_wayback_url=final_wayback_url,
                    web_proxy_mode=True,
                )
                content_type = "text/css; charset=utf-8"
            except Exception as exc:
                logger.warning("CSS rewrite failed: %s", exc)
                body_out = raw_body

        else:
            body_out = raw_body

        if method == "HEAD":
            body_out = b""

        self._send_response(
            resp.status_code,
            resp.reason or "OK",
            content_type.encode() if isinstance(content_type, str) else content_type,
            body_out,
            extra_headers=self._filter_response_headers(resp.headers),
        )

    def _handle_resource_proxy(self, path: str):
        """
        /r?url=<encoded_wayback_url> — extract the URL and serve it directly.
        """
        parsed = urllib.parse.urlparse(path)
        params = urllib.parse.parse_qs(parsed.query)
        url = params.get("url", [""])[0].strip()

        if not url:
            self._send_response(
                400, "Bad Request", b"text/html",
                _error_page(400, "Bad Request", "No URL provided to /r"),
            )
            return

        self._serve_wayback_url(url)

    def _serve_wayback_url(self, url: str):
        """
        Fetch *url* from the Wayback Machine, rewrite all links to stay on our
        server, and write the response directly to the client — no redirects.

        This is the core of web_proxy_mode: the browser never leaves our server
        so Replit's reverse proxy never has to forward a Location header.
        """
        try:
            resp = fetch(url, extra_headers=dict(self.headers))
        except requests.exceptions.Timeout:
            self._send_response(
                504, "Gateway Timeout", b"text/html",
                _error_page(504, "Gateway Timeout", f"Timed out fetching {url}"),
            )
            return
        except Exception as exc:
            self._send_response(
                502, "Bad Gateway", b"text/html",
                _error_page(502, "Bad Gateway", f"Error fetching resource: {exc}"),
            )
            return

        try:
            raw_body = resp.content
            if len(raw_body) > config.MAX_CONTENT_SIZE:
                raw_body = raw_body[: config.MAX_CONTENT_SIZE]
        except Exception as exc:
            self._send_response(
                502, "Bad Gateway", b"text/html",
                _error_page(502, "Bad Gateway", f"Error reading body: {exc}"),
            )
            return

        content_type = resp.headers.get("Content-Type", "application/octet-stream")
        ct_lower = content_type.lower()
        final_url = resp.url
        original_url = extract_original_url_from_wayback(final_url)
        if not original_url or original_url == final_url:
            original_url = url

        if "text/html" in ct_lower or "application/xhtml" in ct_lower:
            try:
                body_out = rewrite_html(
                    raw_body, content_type,
                    page_wayback_url=final_url,
                    base_url=original_url,
                    web_proxy_mode=True,
                )
                content_type = "text/html; charset=utf-8"
            except Exception as exc:
                logger.warning("HTML rewrite failed: %s", exc)
                body_out = raw_body
        elif "text/css" in ct_lower:
            try:
                body_out = rewrite_css(
                    raw_body, content_type,
                    base_url=original_url,
                    page_wayback_url=final_url,
                    web_proxy_mode=True,
                )
                content_type = "text/css; charset=utf-8"
            except Exception as exc:
                logger.warning("CSS rewrite failed: %s", exc)
                body_out = raw_body
        else:
            body_out = raw_body

        self._send_response(
            resp.status_code,
            resp.reason or "OK",
            content_type.encode() if isinstance(content_type, str) else content_type,
            body_out,
            extra_headers=self._filter_response_headers(resp.headers),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _filter_response_headers(headers) -> dict:
        """Return a dict of safe upstream headers to forward to the client."""
        result = {}
        for k, v in headers.items():
            if k.lower() not in config.STRIP_RESPONSE_HEADERS:
                result[k] = v
        return result

    def _send_response(
        self,
        status: int,
        reason: str,
        content_type: bytes,
        body: bytes,
        extra_headers: dict = None,
    ):
        ct = content_type.decode() if isinstance(content_type, bytes) else content_type
        self.send_response(status, reason)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        if extra_headers:
            for k, v in extra_headers.items():
                # Skip headers we set ourselves
                if k.lower() not in ("content-type", "content-length", "connection"):
                    try:
                        self.send_header(k, v)
                    except Exception:
                        pass
        self.end_headers()
        if body:
            self.wfile.write(body)


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """Multi-threaded HTTP server so simultaneous connections don't block each other."""
    daemon_threads = True
    allow_reuse_address = True

    def server_bind(self):
        # Allow immediate re-bind after restart
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        super().server_bind()
