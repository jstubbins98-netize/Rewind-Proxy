# Rewind-Proxy with a PowerBook G4 Running Mac OS X Tiger

This guide explains how to use a **PowerBook G4 running Mac OS X 10.4
Tiger** with **Rewind-Proxy running on a Raspberry Pi 5**.

The Pi connects to the modern internet and handles the HTTPS/TLS connection
to the Internet Archive. The PowerBook connects to the Pi over Ethernet and
receives archived pages over plain HTTP.

```text
Internet
    |
    | Wi-Fi
    v
Raspberry Pi 5
    | Ethernet: 192.168.100.1
    | Rewind-Proxy: port 8080
    |
    | Ethernet cable
    v
PowerBook G4
Mac OS X 10.4 Tiger
HTTP proxy: 192.168.100.1:8080
```

The PowerBook does not need to support modern TLS certificates or encryption.
Rewind-Proxy performs the modern connection on its behalf, downloads an
archived page from the Wayback Machine, rewrites its links, and returns it
over plain HTTP.

> **Important:** The Raspberry Pi needs its own internet connection. The
> recommended arrangement is Wi-Fi from the Pi to your normal router and a
> direct Ethernet cable from the Pi to the PowerBook.

---

## Compatibility Notes

Mac OS X Tiger is version **10.4**. The final Tiger update is **10.4.11**,
which is recommended for this setup.

Tiger supports PowerPC G3, G4, and G5 Macs with built-in FireWire and at least
256 MB of RAM. A PowerBook G4 is a good match for Tiger. If Tiger is already
installed and working on your PowerBook, Rewind-Proxy does not require any
additional software on it.

Suitable browsers include:

- Safari included with Tiger
- TenFourFox
- Camino
- iCab
- Older versions of Firefox

Safari 2 is sufficient for testing the setup. Tiger can also run Safari 3,
depending on the installed updates. TenFourFox may render some later archived
pages more successfully, but no special browser is required.

---

## What You Need

- Raspberry Pi 5
- Raspberry Pi OS, preferably Bookworm
- Internet connection for the Pi
- Power supply for the Pi
- PowerBook G4 running Mac OS X 10.4 Tiger
- One Ethernet cable
- Rewind-Proxy copied onto the Pi
- A way to access the Pi during setup:
  - SSH from another computer, or
  - keyboard and monitor connected to the Pi

A standard Ethernet cable should work. The PowerBook and Pi Ethernet hardware
normally handle crossover automatically. If a very early PowerBook model
cannot establish a link with a normal cable, try a crossover Ethernet cable
or place a small Ethernet switch between the computers.

---

## How Rewind-Proxy and dnsmasq Work Together

Rewind-Proxy performs two jobs on the Pi:

1. It prepares a private Ethernet network between the Pi and PowerBook.
2. It acts as an HTTP proxy for archived web pages.

When started as root on a Raspberry Pi 5, Rewind-Proxy:

1. Detects the Pi 5 hardware.
2. Finds the Pi's wired Ethernet interface.
3. Waits for an Ethernet cable.
4. Assigns `192.168.100.1/24` to the Pi's Ethernet interface.
5. Installs `dnsmasq` automatically if it is missing.
6. Runs dnsmasq as a DHCP-only server.
7. Gives the PowerBook an address between `192.168.100.10` and
   `192.168.100.50`.
8. Watches the local network and reports when the PowerBook appears.

The dnsmasq instance does not run a DNS service. Rewind-Proxy starts it with
`port=0`, which avoids conflicts with the DNS services already used by
Raspberry Pi OS.

The PowerBook sends web requests to `192.168.100.1:8080`. The Pi then contacts
the Wayback Machine using its modern internet connection.

---

## Part 1: Prepare the Raspberry Pi 5

### 1. Connect the Pi to the internet

Connect the Pi to your normal Wi-Fi network. Its Ethernet port will be used
for the private connection to the PowerBook.

On the Pi, confirm that the Internet Archive is reachable:

```bash
curl -I https://web.archive.org/
```

If `curl` is unavailable:

```bash
sudo apt update
sudo apt install -y curl
```

### 2. Copy Rewind-Proxy onto the Pi

Copy the `rewind-proxy` directory to the Pi using Git, SCP, a USB drive, or
another method.

If the program is in a Git repository:

```bash
cd ~
git clone https://github.com/your-username/rewind-proxy.git
cd ~/rewind-proxy/rewind-proxy
```

If you copied the program manually, change to the directory containing
`run.py`, `setup.sh`, and `requirements.txt`:

```bash
cd ~/rewind-proxy
```

Confirm the files are present:

```bash
ls
```

You should see files including:

```text
config.py
pi_setup.py
proxy.py
requirements.txt
rewriter.py
run.py
setup.sh
wayback.py
```

### 3. Run the setup script

Make the setup script executable:

```bash
chmod +x setup.sh
```

Run it:

```bash
./setup.sh
```

The script:

- Checks for Python 3.10 or newer
- Installs Python, pip, and virtual-environment support when necessary
- Creates a Python virtual environment in `venv`
- Installs the packages from `requirements.txt`
- Verifies that the required Python packages can be imported

---

## Part 2: Start Rewind-Proxy

For the first setup, run Rewind-Proxy in normal mode so the web status and
setup pages are available:

```bash
sudo ./venv/bin/python run.py
```

The `sudo` command is required for automatic Pi Ethernet configuration,
dnsmasq installation, and DHCP setup.

Rewind-Proxy initially waits for a cable. Leave this terminal open so you can
watch the status messages.

The private network uses:

| Setting | Value |
|---|---|
| Pi Ethernet address | `192.168.100.1` |
| Network | `192.168.100.0/24` |
| DHCP range | `192.168.100.10`–`192.168.100.50` |
| Rewind-Proxy port | `8080` |

If dnsmasq is not installed, Rewind-Proxy attempts to install it automatically
with `apt-get`. This requires the Pi to have internet access and Rewind-Proxy
to be running as root.

---

## Part 3: Connect the PowerBook G4

1. Make sure Rewind-Proxy is running on the Pi.
2. Connect one end of the Ethernet cable to the Pi.
3. Connect the other end to the PowerBook.
4. Wait for the Pi and PowerBook Ethernet link lights.
5. Allow approximately 10–30 seconds for DHCP.

The Pi should report that an old computer has been detected. The PowerBook
should receive an address such as `192.168.100.10`.

---

## Part 4: Configure Ethernet in Mac OS X Tiger

Configure Tiger to obtain its address automatically:

1. Open the **Apple menu**.
2. Select **System Preferences**.
3. Open **Network**.
4. Use the **Show** menu to select **Built-in Ethernet**.
5. Open the **TCP/IP** tab.
6. Set **Configure IPv4** to **Using DHCP**.
7. Click **Apply Now**.

After a few seconds, the Network panel should show:

- Status: Connected
- An IP address in the `192.168.100.x` range
- Router: `192.168.100.1`

It may show a message indicating that the network has no direct internet
connection. That is acceptable. The supported web path is through
Rewind-Proxy, not direct internet routing.

### Check the address in Terminal

Open:

```text
Applications -> Utilities -> Terminal
```

Run:

```bash
ifconfig en0
```

Look for an `inet` address such as:

```text
inet 192.168.100.10 netmask 0xffffff00
```

On most PowerBook G4 systems, Built-in Ethernet is `en0`. If it is not, run
`ifconfig` without an interface name to list every interface.

Test the connection to the Pi:

```bash
ping 192.168.100.1
```

Press **Control-C** to stop the test. Replies from `192.168.100.1` confirm the
private Ethernet connection is working.

---

## Part 5: Configure the HTTP Proxy in Tiger

Mac OS X Tiger provides system-wide proxy settings. Safari and many other
Mac applications use them automatically.

1. Open the **Apple menu**.
2. Select **System Preferences**.
3. Open **Network**.
4. Use the **Show** menu to select **Built-in Ethernet**.
5. Open the **Proxies** tab.
6. Set **Configure Proxies** to **Manually** if that menu is shown.
7. Check **Web Proxy (HTTP)**.
8. Enter:

   - Web Proxy Server: `192.168.100.1`
   - Port: `8080`

9. Do **not** check **Secure Web Proxy (HTTPS)**.
10. Leave proxy authentication disabled.
11. Click **Apply Now**.

The final setting should be:

| Tiger proxy setting | Value |
|---|---|
| Web Proxy (HTTP) | Enabled |
| Proxy server | `192.168.100.1` |
| Port | `8080` |
| Secure Web Proxy (HTTPS) | Disabled |
| Proxy authentication | Disabled |

### Why HTTPS proxying must remain disabled

Rewind-Proxy does not provide HTTPS `CONNECT` tunneling. Instead, the
PowerBook requests a plain `http://` address and the Pi fetches the archived
copy from the Wayback Machine over modern HTTPS.

Use addresses beginning with:

```text
http://
```

Examples:

```text
http://www.apple.com/
http://www.yahoo.com/
http://www.google.com/
```

Do not type `https://` in the PowerBook browser for normal Rewind-Proxy use.

---

## Part 6: Browse the Archived Web

Open Safari or another browser on the PowerBook and enter:

```text
http://www.apple.com/
```

The request follows this path:

```text
PowerBook browser
    -> HTTP proxy on Raspberry Pi
    -> Internet Archive Wayback Machine
    -> rewritten archived page
    -> PowerBook browser
```

When no date is specified, Rewind-Proxy uses its default archived period near
the year 2000.

To choose a specific date, open the Rewind-Proxy home page:

```text
http://192.168.100.1:8080/
```

The home page provides:

- A URL field
- Day, month, and year controls
- Quick links to classic websites
- Raspberry Pi Ethernet status
- Setup instructions

Archived page links and images are rewritten to continue through the proxy,
so the PowerBook should not be sent directly to `web.archive.org`.

---

## Using TenFourFox or Another Browser

TenFourFox was designed for PowerPC Macs and can display more complex pages
than Tiger's original Safari. If TenFourFox is installed, it may use either
the Mac's system proxy settings or its own browser proxy settings, depending
on the version and configuration.

If it does not use the Tiger system proxy:

1. Open the browser preferences.
2. Find **Advanced**, **Network**, or **Connection Settings**.
3. Select **Manual proxy configuration**.
4. Enter `192.168.100.1` as the HTTP proxy.
5. Enter `8080` as the port.
6. Do not configure an HTTPS or SSL proxy.

The exact labels vary between TenFourFox, Firefox, Camino, and iCab releases.

---

## Optional: Run Rewind-Proxy in Headless Mode

For an always-on Pi without a monitor or keyboard:

```bash
sudo ./venv/bin/python run.py --headless
```

Headless mode disables the HTML home page, quick links, and full setup page.
The proxy itself continues to work normally.

The PowerBook must use the HTTP proxy settings because the form-based home
page is unavailable. Opening the Pi address directly:

```text
http://192.168.100.1:8080/
```

returns a small plain-text status response. It can show:

- Current proxy host and port
- Whether Pi Ethernet is waiting for a cable
- Whether it is waiting for the PowerBook
- The PowerBook's detected IP address

---

## Optional: Start Rewind-Proxy at Boot

Create a systemd service on the Pi:

```bash
sudo nano /etc/systemd/system/rewind-proxy.service
```

Use the following configuration, adjusting paths if the project is not
installed at `/home/pi/rewind-proxy`:

```ini
[Unit]
Description=Rewind-Proxy for PowerBook G4
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/pi/rewind-proxy
ExecStart=/home/pi/rewind-proxy/venv/bin/python /home/pi/rewind-proxy/run.py --headless
Restart=on-failure
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
```

Enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable rewind-proxy
sudo systemctl start rewind-proxy
```

Check its status:

```bash
sudo systemctl status rewind-proxy
```

Follow its logs:

```bash
sudo journalctl -u rewind-proxy -f
```

After the service is enabled, the normal order is:

1. Power on the Pi.
2. Wait for it to join Wi-Fi and start Rewind-Proxy.
3. Power on the PowerBook.
4. Connect Ethernet if it is not already connected.
5. Open the PowerBook browser and use an `http://` address.

---

## Manual Network Configuration

If the PowerBook does not receive an address from dnsmasq, assign one
manually:

1. Open **System Preferences**.
2. Open **Network**.
3. Use the **Show** menu to select **Built-in Ethernet**.
4. Open the **TCP/IP** tab.
5. Change **Configure IPv4** from **Using DHCP** to **Manually**.
6. Enter:

| Setting | Value |
|---|---|
| IP Address | `192.168.100.2` |
| Subnet Mask | `255.255.255.0` |
| Router | `192.168.100.1` |
| DNS Server | `8.8.8.8` |

7. Click **Apply Now**.

Keep the HTTP proxy set to:

```text
192.168.100.1:8080
```

The static address `192.168.100.2` is outside Rewind-Proxy's normal DHCP
range, which prevents a duplicate-address conflict.

---

## Troubleshooting

### Built-in Ethernet says "Cable Unplugged"

- Check both ends of the Ethernet cable.
- Try another cable.
- Check for link lights on the Pi and PowerBook.
- Make sure **Built-in Ethernet** is enabled in the Network preference pane.
- Try a crossover cable or a small Ethernet switch if the PowerBook is too
  old to handle automatic cable crossover.

### The PowerBook receives a `169.254.x.x` address

An address beginning with `169.254` means Tiger did not receive a DHCP
lease.

Check that:

- Rewind-Proxy was started with `sudo`.
- The Pi detected the Ethernet cable.
- The Pi has internet access so it can install dnsmasq if needed.
- dnsmasq started successfully.

On the Pi:

```bash
command -v dnsmasq
ip -4 addr show
sudo ss -lunp | grep ':67'
```

You can also use the manual Tiger network configuration described above.

### The PowerBook can ping the Pi but Safari cannot load pages

Verify the proxy configuration:

- **Web Proxy (HTTP)** is enabled.
- Server is `192.168.100.1`.
- Port is `8080`.
- **Secure Web Proxy (HTTPS)** is disabled.
- You entered an address beginning with `http://`.

Test the proxy's local page:

```text
http://192.168.100.1:8080/
```

If this page works but external archived sites do not, check the Pi's internet
connection and Rewind-Proxy logs.

### Safari reports a certificate or secure-connection error

The browser is probably attempting to open an `https://` address directly.
Change it to `http://`.

The Pi handles the secure connection to the Internet Archive. The PowerBook
should only make plain HTTP requests.

### Safari says it cannot decode the page

Make sure the Pi is running the current version of Rewind-Proxy. It removes
the upstream `Content-Encoding` header after Python decompresses the response,
which prevents old Safari versions from attempting to decompress the same
content twice.

### Pages load without some images

The Wayback Machine may not have captured every image, stylesheet, or file.
Try another archive date using the Rewind-Proxy home page.

### A page is blank or badly formatted

Try:

- An earlier snapshot
- A site from the late 1990s or early 2000s
- TenFourFox instead of Safari
- One of the classic quick links on the home page

Later archived sites may depend on JavaScript and browser features unavailable
on PowerPC Tiger.

### Tiger says the Ethernet network has no internet

This is expected. The Ethernet cable is a private link to the Pi, not a normal
router connection.

The supported route is:

```text
PowerBook browser -> Rewind-Proxy -> Wayback Machine
```

As long as the browser's HTTP proxy is set correctly, Tiger does not need to
recognize the Ethernet connection as a normal internet service.

### The PowerBook cannot reach the Pi while AirPort is enabled

Tiger may prefer another network service. In **System Preferences -> Network**,
use **Show -> Network Port Configurations** to move **Built-in Ethernet** above
**AirPort**, or temporarily turn AirPort off while testing.

The HTTP proxy must be configured on the **Built-in Ethernet** service because
proxy settings are stored separately for each Tiger network service.

---

## Quick Reference

### Raspberry Pi commands

```bash
# Prepare Python and the virtual environment
./setup.sh

# Start normally
sudo ./venv/bin/python run.py

# Start without the web UI
sudo ./venv/bin/python run.py --headless

# Check an installed systemd service
sudo systemctl status rewind-proxy
sudo journalctl -u rewind-proxy -f
```

### PowerBook G4 Ethernet settings

Automatic configuration:

```text
System Preferences -> Network -> Built-in Ethernet
TCP/IP -> Configure IPv4: Using DHCP
```

Manual fallback:

```text
IP address:  192.168.100.2
Subnet mask: 255.255.255.0
Router:      192.168.100.1
DNS:         8.8.8.8
```

### Tiger HTTP proxy settings

```text
System Preferences -> Network
Show: Built-in Ethernet
Proxies

Web Proxy (HTTP): enabled
Server:           192.168.100.1
Port:             8080
Secure Web Proxy: disabled
```

### Rewind-Proxy home or status page

```text
http://192.168.100.1:8080/
```

Once the Pi is online, Rewind-Proxy is running, and the PowerBook's HTTP proxy
points to `192.168.100.1:8080`, the PowerBook is ready to browse the archived
web.