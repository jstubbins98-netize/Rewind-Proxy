# Rewind-Proxy

A web proxy server that lets **old computers from the 1990s and 2000s browse the internet** by routing every request through the [Internet Archive Wayback Machine](https://web.archive.org/).

Old browsers (Netscape Navigator, Internet Explorer 5/6, early Opera, iCab) cannot connect to any modern website — they lack TLS 1.2/1.3, their certificate stores are stale, and modern security headers crash them. Rewind-Proxy sits in the middle: it speaks plain HTTP/1.0 to the old browser and handles all the modern HTTPS and TLS itself, then serves back a cleaned-up archived page from the era you want.

The intended setup is a **Linux computer** plugged directly into the old computer with an ethernet cable — no router or network switch needed. A Raspberry Pi 5 is one supported option, but a Linux laptop, desktop, mini PC, or server works too.

---

## How It Works

```
Old browser ── plain HTTP/1.0 ──► Rewind-Proxy :8080
                                        │
                           1. Find best Wayback snapshot
                           2. Fetch over modern HTTPS/TLS
                           3. Rewrite all links → back through proxy
                           4. Strip Wayback toolbar + modern headers
                                        │
                                        ▼
                            Clean archived HTML served
                            over plain HTTP to old browser
```

For every request the proxy:

1. **Finds the closest snapshot** — queries the Wayback CDX API for the nearest archived page to the date you chose, then falls back to the availability API, then falls back to a direct `web.archive.org/web/TIMESTAMP/` URL.
2. **Fetches it over modern HTTPS** — the old computer never touches TLS; the proxy handles it.
3. **Rewrites all links and resources** — every `href`, `src`, `action`, and CSS `url()` in the page is rewritten so the next click also goes through the proxy rather than out to the open internet (where the old browser would fail).
4. **Strips incompatible content** — the Wayback Machine injects its own JavaScript toolbar, CSS banner, and modern security headers. These are all removed before the page is sent to the old browser.
5. **Adds a thin info bar** at the top of every page showing the archive date, a link to browse the site's full history, and a link home.

---

## Features

- Works with any browser that supports HTTP proxy settings — including Netscape 4, IE 5/6, Opera 7/8, Mosaic, Lynx, iCab, and Mac OS 9 browsers
- Two usage modes: **browser proxy settings** (type any URL in the address bar) and **direct home page** (open `http://pi-ip:8080/` and use the form)
- Date picker on the home page — choose any year from 1996 to the present
- Quick links to popular 1990s/2000s sites (Yahoo!, Google, BBC, CNN, Wikipedia, GeoCities, AltaVista, Ask Jeeves)
- **Automatic Linux ethernet wizard** — selects a safe wired port, protects the host's default-route interface, configures a private static IP, installs/runs dnsmasq for DHCP, and shows live connection status
- Strips `Content-Security-Policy`, `Strict-Transport-Security`, `X-Frame-Options`, and all other headers that crash old browsers
- Fixes gzip encoding issues (decompresses before forwarding so old browsers don't see raw compressed data)
- Threaded server — handles multiple requests simultaneously

---

## Requirements

- Python 3.10 or later
- `pip install -r requirements.txt` (installs `requests` and `beautifulsoup4`)
- Internet connection on the machine running the proxy
- For automatic Linux ethernet setup: Linux, `sudo` access, and a wired port not carrying the host's default internet route

---

## Quick Start (any machine)

```bash
cd rewind-proxy
chmod +x setup.sh
./setup.sh
./venv/bin/python run.py
```

The proxy starts on `0.0.0.0:8080`. Open `http://<this-machine-ip>:8080/` in any browser to reach the home page, or configure your browser's HTTP proxy settings to point to this machine.

```
./venv/bin/python run.py --host 0.0.0.0 --port 8080 --interface enp3s0 --headless --debug
```

| Option       | Default   | Description                                                    |
|--------------|-----------|----------------------------------------------------------------|
| `--host`     | `0.0.0.0` | Bind address                                                   |
| `--port`     | `8080`    | Port to listen on                                              |
| `--interface NAME` | auto | Wired Linux interface for the old computer, such as `eth0` or `enp3s0` |
| `--headless` | off       | Disable the web UI; serve only a plain-text status at `/`      |
| `--debug`    | off       | Verbose debug logging                                          |

On Linux, Rewind-Proxy automatically selects a wired interface that is not
carrying the default internet route. This prevents it from replacing the IP
address on the interface the host is using for internet access. If more than
one suitable wired port exists, select one explicitly with `--interface`.

Examples:

```bash
# Automatically select a safe wired port
sudo ./venv/bin/python run.py

# Use a specific wired port
sudo ./venv/bin/python run.py --interface enp3s0

# Generic Linux host in headless mode
sudo ./venv/bin/python run.py --interface eth0 --headless
```

The automatic dnsmasq installer supports `apt`, `dnf`, `yum`, `zypper`,
`pacman`, and `apk`.

---

## Linux Ethernet Setup — Full Guide

The Linux host runs Rewind-Proxy and connects directly to the old computer over a single ethernet cable. The host needs a separate internet connection, normally Wi-Fi or a second network adapter. No Wi-Fi is needed on the old machine.

### What You Need

| Item | Notes |
|------|-------|
| Linux host | Raspberry Pi 5, laptop, desktop, mini PC, or server |
| Ethernet cable | Standard Cat 5e/Cat 6 straight-through cable |
| The old computer | Any machine with a working ethernet port and a browser with proxy settings |
| Power for the Pi | USB-C power supply |
| A way to control the Pi | SSH from another machine, keyboard + monitor, or VNC |

The Pi needs an internet connection of its own — use its Wi-Fi or connect it to your router with a second ethernet cable (if your Pi has only one port, Wi-Fi for internet + ethernet for the old computer is the typical setup).

### Step 1 — Install Rewind-Proxy on the Linux Host

```bash
# On Debian, Ubuntu, or Raspberry Pi OS:
sudo apt update
sudo apt install -y python3-pip dnsmasq
git clone https://github.com/your-username/rewind-proxy.git
cd rewind-proxy/rewind-proxy
pip3 install -r requirements.txt
```

> Rewind-Proxy installs dnsmasq automatically when it is missing and the
> program is running as root. Supported package managers are apt, dnf, yum,
> zypper, pacman, and apk.

### Step 2 — Run the Proxy (as root for full auto-setup)

```bash
sudo ./venv/bin/python run.py
```

Running as `root` lets the proxy:
- Assign a static IP (`192.168.100.1`) to the selected Linux ethernet interface automatically
- Start `dnsmasq` to hand out IP addresses via DHCP

If you run **without** `sudo`, the proxy still works but prints the `ip` commands you need to run manually and shows them on the home page.

On startup you will see:

```
============================================================
  Rewind-Proxy started  (local network — make sure port is not firewalled)

  Open this URL in any browser:
  >>> http://192.168.100.1:8080/ <<<

  — OR — configure your old browser's proxy settings:
  Proxy host : 192.168.100.1
  Proxy port : 8080
  Then browse any http:// URL normally.
============================================================
  Linux ethernet setup enabled on eth0.
  Connect your old computer to that ethernet port.
  The home page will show live setup instructions.
============================================================
```

### Step 3 — Connect the Old Computer to the Pi

Plug one end of the ethernet cable into the **old computer's network port** and the other end into the **Pi's ethernet port**.

If `dnsmasq` is running the old computer will get an IP address automatically (in the range `192.168.100.10`–`192.168.100.50`). If not, set the old computer's TCP/IP settings manually:

| Setting | Value |
|---------|-------|
| IP address | `192.168.100.2` |
| Subnet mask | `255.255.255.0` |
| Default gateway | `192.168.100.1` |
| DNS server | `8.8.8.8` |

**Where to find TCP/IP settings on old systems:**

- **Windows 95/98/ME** — Control Panel → Network → TCP/IP (for the ethernet adapter) → Properties
- **Windows XP** — Control Panel → Network Connections → Local Area Connection → Properties → TCP/IP
- **Mac OS 8/9** — Apple menu → Control Panels → TCP/IP → set "Connect via" to Ethernet, "Configure" to Manually
- **Mac OS X 10.2–10.5** — System Preferences → Network → Built-in Ethernet → TCP/IP tab

The Pi's home page at `http://192.168.100.1:8080/` will show a green **"Old computer connected"** banner once it sees the device on the network.

### Step 4 — Configure the Old Browser's Proxy Settings

In the old browser, set the **HTTP proxy** to the Pi's ethernet IP address:

| Field | Value |
|-------|-------|
| HTTP Proxy host | `192.168.100.1` |
| Port | `8080` |

**Browser-specific instructions:**

- **Netscape Navigator 4.x** — Edit → Preferences → Advanced → Proxies → Manual proxy configuration → HTTP Proxy
- **Internet Explorer 5/6** — Tools → Internet Options → Connections → LAN Settings → check "Use a proxy server" → enter host and port
- **Internet Explorer 3/4** — View → Options → Connection → Connect through a proxy server
- **Opera 7/8** — Tools → Preferences → Advanced → Network → Proxy servers → HTTP
- **iCab (Mac)** — Edit → Preferences → Network → Proxies
- **Mac IE 5** — Edit → Preferences → Network → Proxies

### Step 5 — Browse

With the proxy configured, type any URL in the old browser's address bar and press Enter. Rewind-Proxy will find and serve the nearest archived version from the year 2000 by default.

You can also open the **home page** directly:

```
http://192.168.100.1:8080/
```

From there, use the form to browse to any site and choose any date from 1996 onwards. Quick links take you straight to classic 1990s/2000s websites.

### Running at Boot (optional)

To start Rewind-Proxy automatically when the Pi powers on, create a systemd service.

**Normal mode** (home page enabled):

```bash
sudo nano /etc/systemd/system/rewind-proxy.service
```

```ini
[Unit]
Description=Rewind-Proxy
After=network.target

[Service]
ExecStart=/home/pi/rewind-proxy/rewind-proxy/venv/bin/python /home/pi/rewind-proxy/rewind-proxy/run.py
WorkingDirectory=/home/pi/rewind-proxy/rewind-proxy
Restart=on-failure
User=root

[Install]
WantedBy=multi-user.target
```

**Headless mode** (recommended for always-on Pi service — no web UI overhead):

```ini
[Unit]
Description=Rewind-Proxy (headless)
After=network.target

[Service]
ExecStart=/home/pi/rewind-proxy/rewind-proxy/venv/bin/python /home/pi/rewind-proxy/rewind-proxy/run.py --headless
WorkingDirectory=/home/pi/rewind-proxy/rewind-proxy
Restart=on-failure
User=root

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable rewind-proxy
sudo systemctl start rewind-proxy
```

---

## Using the Home Page (Direct Mode)

If the old browser can reach the Pi but you'd rather not configure proxy settings, open the home page directly:

```
http://192.168.100.1:8080/
```

Use the **URL form** to enter any site address and pick a date. The page is served directly through the proxy — the old browser never needs proxy settings configured, and the address bar never shows `archive.org` URLs.

---

## Headless Mode

Headless mode disables the web UI entirely — no home page, no quick links, no setup guide. The proxy still works in full; you just configure the old browser's proxy settings and browse normally. The only thing served at `/` is a brief plain-text status block.

```bash
./venv/bin/python run.py --headless
sudo ./venv/bin/python run.py --headless
```

**Startup banner in headless mode:**

```
============================================================
  Rewind-Proxy started  [HEADLESS]  (local network...)

  Web UI disabled. Configure your browser's proxy settings:
  Proxy host : 192.168.100.1
  Proxy port : 8080

  Status endpoint: http://192.168.100.1:8080/
============================================================
```

**Status endpoint (`/`)** — a monitoring tool or `curl` can hit this to confirm the proxy is alive:

```
Rewind-Proxy [headless]  (local network — make sure port is not firewalled)
Time        : 2026-08-07 21:00:00 UTC
Proxy host  : 192.168.100.1
Proxy port  : 8080
Pi ethernet : old computer connected at 192.168.100.12
```

**`/setup`** — returns brief plain-text proxy connection details instead of the full HTML guide.

**Everything else is unchanged** — `/go`, `/r`, and standard browser proxy mode all work exactly as in normal mode. The only difference is that the old computer cannot use the form-based home page and must have browser proxy settings configured.

### When to use headless mode

| Scenario | Recommendation |
|---|---|
| Pi running as a always-on background service (systemd, no keyboard/monitor) | **Headless** — no UI overhead, status endpoint still works for `curl` health checks |
| Pi with a monitor where you occasionally want to use the home page from a modern browser | Normal mode |
| Laptop or desktop running Rewind-Proxy for a one-off session | Normal mode |
| Automated/scripted deployment where you want minimal attack surface | **Headless** |

---

## Architecture

### File Overview

| File | Purpose |
|------|---------|
| `run.py` | Entry point — argument parsing, server startup, Pi wizard init |
| `proxy.py` | HTTP server, request routing, two modes (direct + browser-proxy) |
| `rewriter.py` | HTML/CSS rewriter — rewrites links, strips Wayback toolbar, adds info bar |
| `wayback.py` | Wayback Machine client — snapshot resolution, HTTP fetching |
| `pi_setup.py` | Linux ethernet wizard — safe interface selection, network config, DHCP, ARP monitor |
| `config.py` | All tuneable constants |

### Two Usage Modes

**Direct mode** — browser opens the proxy's home page URL or a `/go?url=...` link directly. All pages are served from `/r?url=<encoded-wayback-url>` endpoints. Every link in every page is rewritten to `/r?url=...` so the browser stays on the proxy server and the address bar never shows `archive.org`.

**Browser proxy mode** — browser's HTTP proxy settings point to the Pi. The browser sends `GET http://apple.com/ HTTP/1.0` directly to the proxy. The proxy resolves this to a Wayback snapshot, fetches it, and rewrites all links as root-relative `/r?url=...` paths. When the browser follows a link, the path resolves back to the proxy regardless of which host the current page came from.

Both modes share the same underlying fetch-and-rewrite pipeline.

### What Gets Stripped

- Wayback Machine toolbar JavaScript (`wombat.js`, `__wm.*`, `analytics.archive.org`)
- Wayback banner CSS (`web-static.archive.org/static/css/banner-styles.css`, `iconochive.css`)
- Wayback toolbar HTML elements (IDs: `wm-ipp-base`, `wm-ipp`, `donato`, `wm-tb`)
- Modern HTTP response headers: `Content-Security-Policy`, `Strict-Transport-Security`, `X-Frame-Options`, `Feature-Policy`, `Permissions-Policy`, CORS headers
- `Content-Encoding: gzip` (the proxy decompresses transparently; forwarding this header causes Safari to crash with "cannot decode raw data")

---

## Troubleshooting

**Old browser says "Unable to connect" or the proxy just hangs**
- Check the ethernet cable is plugged in at both ends.
- Confirm the old computer has an IP address in the `192.168.100.x` range.
- Verify the proxy host/port in the browser's settings matches `192.168.100.1:8080`.
- Try pinging `192.168.100.1` from the old computer to confirm the link is up.

**Pages load but images are missing**
Normal — the Wayback Machine only archived what its crawler found. Not every image from every page was captured.

**Safari / old Mac browser says "cannot decode raw data"**
This is the gzip `Content-Encoding` header bug. It was fixed in this proxy — make sure you are running the latest version.

**Browser shows a blank page or "This page cannot be displayed"**
Some pages are very large or have encoding the old browser can't handle. Try a different date — earlier snapshots are often simpler and lighter.

**Address bar shows `web.archive.org` URLs**
Make sure you are running the latest version of the proxy. Old versions used a different link rewriting strategy; the current version keeps all links on the proxy's own address.

**Pi home page shows "Not running on a Raspberry Pi"**
You are running on a laptop or cloud machine. The ethernet wizard is disabled but everything else works — connect the old computer to the same network and use that machine's IP address instead of `192.168.100.1`.

**`dnsmasq` fails to start**
Run `sudo apt install dnsmasq` on the Pi. If another service is using port 53 (common on Pi OS Bookworm with `systemd-resolved`), disable it first: `sudo systemctl disable --now systemd-resolved`.

---

## Limitations

- **No HTTPS tunnelling** — `CONNECT` is not supported. Old browsers must use `http://` URLs. The proxy handles all TLS internally so this is not a problem for browsing archived sites.
- **No JavaScript execution** — the proxy does not run JavaScript. Pages that relied on JS for their content will appear incomplete, but that is true in the original old browsers too.
- **POST forms** — work for a single submission, but session state (cookies, login sessions) may not persist correctly across pages.
- **Very large pages** — truncated at 10 MB (configurable in `config.py`).
- **Some sites were never archived** — if the Wayback Machine has no snapshots for a URL, the proxy returns an error page.

---

## Licence

MIT — see `LICENSE` for details.
