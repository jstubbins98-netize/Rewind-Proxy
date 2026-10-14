"""Old-browser-friendly snapshot chooser; no JavaScript or automatic refresh."""

import html
import urllib.parse

from wayback import resolve_to_wayback


def build_snapshot_page(original_url, snapshots, page, has_more, timestamp=""):
    def link(url):
        return html.escape("/r?" + urllib.parse.urlencode({"url": url}), quote=True)

    entries = []
    for snapshot in snapshots:
        ts = snapshot["timestamp"]
        date = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[8:10]}:{ts[10:12]}:{ts[12:14]} UTC"
        entries.append(
            f'<li><a href="{link(snapshot["url"])}">{date}</a>'
            f' &mdash; {html.escape(snapshot["original"])}</li>'
        )

    def page_link(number, label):
        params = {"url": original_url, "page": str(number)}
        if timestamp:
            params.update(year=timestamp[:4], month=timestamp[4:6], day=timestamp[6:8])
        href = html.escape("/go?" + urllib.parse.urlencode(params), quote=True)
        return f'<a href="{href}">{label}</a>'

    navigation = []
    if page:
        navigation.append(page_link(page - 1, "Previous captures"))
    if has_more:
        navigation.append(page_link(page + 1, "More captures"))
    target = resolve_to_wayback(original_url, preferred_timestamp=timestamp)
    return f"""<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">
<html><head><title>Choose an archived page - Rewind-Proxy</title></head>
<body bgcolor="#FFFFFF">
<h1>Which archived page would you like to visit?</h1>
<p>Multiple captures were found for <b>{html.escape(original_url)}</b>.
Choose a capture date below. Dates are in UTC, oldest first.</p>
<p><a href="{link(target)}">Visit the capture nearest your requested date
({html.escape(timestamp[:8] or "default date")})</a></p>
<h2>Capture list - page {page + 1}</h2>
<ul>{"".join(entries)}</ul>
<p>{" | ".join(navigation)}</p>
<p><a href="/">Rewind-Proxy home</a></p>
</body></html>""".encode("utf-8")
