"""
Linux ethernet connection wizard for Rewind-Proxy.

When running on Linux this module:
  1. Finds a safe wired ethernet interface
  2. Avoids the interface carrying the host's default internet route
  3. Configures it with a static IP (192.168.100.1) — needs root
  4. Optionally starts dnsmasq for DHCP so the old computer gets an IP automatically
  5. Monitors the ARP table for a device appearing on the ethernet subnet
  6. Exposes get_status() so the home page can show live wizard state

If not running as root, the module prints manual commands the user can run
with sudo and still monitors the interface once it has an IP.
"""

import logging
import os
import platform
import re
import shutil
import socket
import subprocess
import threading
import time

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Network constants
# ──────────────────────────────────────────────
ETH_IP          = "192.168.100.1"
ETH_PREFIX      = "24"                    # /24 = 255.255.255.0
ETH_NETMASK     = "255.255.255.0"
ETH_SUBNET      = "192.168.100.0"
# IP we suggest when there is no DHCP
STATIC_OLD_IP   = "192.168.100.2"
STATIC_GW       = ETH_IP
STATIC_DNS      = "8.8.8.8"
DHCP_RANGE_START = "192.168.100.10"
DHCP_RANGE_END   = "192.168.100.50"

# ──────────────────────────────────────────────
# State machine values
# ──────────────────────────────────────────────
S_NOT_LINUX      = "not_linux"
# Backwards-compatible alias for older proxy.py versions.
S_NOT_PI         = S_NOT_LINUX
S_DETECTING      = "detecting"
S_WAITING_CABLE  = "waiting_cable"
S_CONFIGURING    = "configuring"
S_WAITING_DEVICE = "waiting_device"
S_CONNECTED      = "connected"
S_ERROR          = "error"

# Shared mutable state — read by proxy.py home page handler
_state: dict = {
    "status":           S_DETECTING,
    "eth_iface":        None,   # e.g. "eth0"
    "eth_ip":           None,   # IP assigned to the Linux host on that interface
    "proxy_port":       8080,
    "old_computer_ip":  None,   # IP of the connected old computer (from ARP)
    "is_root":          False,
    "dnsmasq_running":  False,
    "manual_cmds":      [],     # commands user must run manually if not root
    "error":            None,
}
_lock = threading.Lock()

_monitor_thread: threading.Thread | None = None
_stop_event = threading.Event()


# ──────────────────────────────────────────────
# Platform detection
# ──────────────────────────────────────────────

def is_raspberry_pi_5() -> bool:
    """Return True if this machine is a Raspberry Pi 5."""
    for path in ("/proc/device-tree/model", "/sys/firmware/devicetree/base/model"):
        try:
            with open(path, "r", errors="replace") as f:
                model = f.read().strip().lower()
            if "raspberry pi 5" in model:
                return True
        except FileNotFoundError:
            continue
    # Fallback: check /proc/cpuinfo Hardware field
    try:
        with open("/proc/cpuinfo") as f:
            cpuinfo = f.read().lower()
        if "raspberry pi 5" in cpuinfo or ("bcm2712" in cpuinfo):
            return True
    except FileNotFoundError:
        pass
    return False


def is_linux() -> bool:
    """Return True when running on a Linux kernel."""
    return platform.system().lower() == "linux"


# ──────────────────────────────────────────────
# Network interface helpers
# ──────────────────────────────────────────────

def _list_interfaces() -> list[str]:
    """Return all network interface names visible in /sys/class/net."""
    try:
        return os.listdir("/sys/class/net")
    except OSError:
        return []


def _default_route_interfaces() -> set[str]:
    """Return interfaces currently carrying an IPv4 default route."""
    interfaces: set[str] = set()
    try:
        if shutil.which("ip"):
            result = subprocess.run(
                ["ip", "-4", "route", "show", "default"],
                capture_output=True, text=True, timeout=5,
            )
            interfaces.update(re.findall(r"\bdev\s+(\S+)", result.stdout))
    except Exception:
        pass

    # Kernel fallback for minimal Linux installations without the `ip` command.
    # /proc/net/route marks the default route with Destination 00000000.
    try:
        with open("/proc/net/route") as route_file:
            next(route_file, None)  # header
            for line in route_file:
                fields = line.split()
                if len(fields) >= 4 and fields[1] == "00000000":
                    interfaces.add(fields[0])
    except OSError:
        pass

    return interfaces


def ensure_ip_command() -> bool:
    """Install the Linux `ip` command when possible."""
    if shutil.which("ip"):
        return True
    if os.geteuid() != 0:
        logger.warning(
            "The `ip` command is missing and Rewind-Proxy is not root; "
            "automatic ethernet configuration is unavailable"
        )
        return False

    installers = [
        ("apt-get", ["apt-get", "install", "-y", "--no-install-recommends", "iproute2"]),
        ("dnf", ["dnf", "install", "-y", "iproute"]),
        ("yum", ["yum", "install", "-y", "iproute"]),
        ("zypper", ["zypper", "--non-interactive", "install", "iproute2"]),
        ("pacman", ["pacman", "-Sy", "--noconfirm", "iproute2"]),
        ("apk", ["apk", "add", "iproute2"]),
    ]
    install_cmd = next(
        (cmd for executable, cmd in installers if shutil.which(executable)),
        None,
    )
    if not install_cmd:
        logger.warning("The `ip` command is missing and no supported package manager was found")
        return False

    logger.info("Installing Linux network tools with %s", install_cmd[0])
    try:
        result = subprocess.run(install_cmd, capture_output=True, timeout=180)
        if result.returncode != 0:
            logger.warning(
                "%s network-tools install failed: %s",
                install_cmd[0],
                result.stderr.decode(errors="replace"),
            )
    except Exception as exc:
        logger.warning("Could not install Linux network tools: %s", exc)
    return bool(shutil.which("ip"))


def _is_wired_ethernet(iface: str) -> bool:
    """Return True for a real wired Ethernet interface, excluding Wi-Fi."""
    if iface == "lo":
        return False
    if os.path.isdir(f"/sys/class/net/{iface}/wireless"):
        return False
    if os.path.exists(f"/sys/class/net/{iface}/phy80211"):
        return False
    try:
        with open(f"/sys/class/net/{iface}/type") as f:
            return f.read().strip() == "1"  # ARPHRD_ETHER
    except OSError:
        return False


def find_ethernet_interface(requested: str | None = None) -> str | None:
    """
    Find a wired Ethernet interface that is safe to reconfigure.

    Wi-Fi devices are excluded even though Linux reports them as ARPHRD_ETHER.
    Interfaces carrying a default route are excluded so Rewind-Proxy does not
    disconnect the Linux host from the internet. A requested interface still
    must be wired and must not carry the default route.
    """
    default_ifaces = _default_route_interfaces()

    if requested:
        if requested not in _list_interfaces():
            logger.warning("Requested ethernet interface %s does not exist", requested)
            return None
        if not _is_wired_ethernet(requested):
            logger.warning("Requested interface %s is not wired Ethernet", requested)
            return None
        if requested in default_ifaces:
            logger.warning(
                "Refusing to reconfigure %s because it carries the default route",
                requested,
            )
            return None
        return requested

    preferred = [
        iface for iface in _list_interfaces()
        if _is_wired_ethernet(iface) and iface not in default_ifaces
    ]

    if not preferred:
        return None

    # Prefer a disconnected port intended for the old computer, then common names.
    def sort_key(name):
        carrier_rank = 1 if get_carrier_state(name) else 0
        if name == "eth0":
            return (carrier_rank, 0, name)
        if name.startswith("eth"):
            return (carrier_rank, 1, name)
        if name.startswith("en"):
            return (carrier_rank, 2, name)
        return (carrier_rank, 3, name)

    preferred.sort(key=sort_key)
    return preferred[0]


def _read_sys(path: str) -> str:
    """Read a single-line sysfs file, return '' on error."""
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def get_carrier_state(iface: str) -> bool:
    """Return True if a cable is plugged in (carrier detected)."""
    # operstate: "up" means carrier + configured; carrier file: "1" means signal
    operstate = _read_sys(f"/sys/class/net/{iface}/operstate")
    carrier   = _read_sys(f"/sys/class/net/{iface}/carrier")
    return carrier == "1" or operstate in ("up", "unknown")


def get_iface_ips(iface: str) -> list[str]:
    """Return IPv4 addresses currently assigned to *iface*."""
    try:
        result = subprocess.run(
            ["ip", "-4", "addr", "show", "dev", iface],
            capture_output=True, text=True, timeout=5,
        )
        return re.findall(r"inet\s+(\d+\.\d+\.\d+\.\d+)/", result.stdout)
    except Exception:
        return []


def iface_has_our_ip(iface: str) -> bool:
    """Return True if ETH_IP is already assigned to *iface*."""
    return ETH_IP in get_iface_ips(iface)


# ──────────────────────────────────────────────
# Network configuration (requires root)
# ──────────────────────────────────────────────

def _run(cmd: list[str]) -> bool:
    """Run a shell command; return True on success."""
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=10)
        if result.returncode != 0:
            logger.warning("Command failed %s: %s", cmd, result.stderr.decode())
        return result.returncode == 0
    except Exception as exc:
        logger.warning("Command exception %s: %s", cmd, exc)
        return False


def configure_ethernet(iface: str) -> bool:
    """
    Assign ETH_IP/PREFIX to *iface* and bring it up.
    Returns True on success.  Requires root.
    """
    # Bring the interface up first
    _run(["ip", "link", "set", iface, "up"])
    time.sleep(0.5)

    # Remove any existing IP on this iface to avoid duplicates
    for existing in get_iface_ips(iface):
        _run(["ip", "addr", "del", f"{existing}/24", "dev", iface])

    ok = _run(["ip", "addr", "add", f"{ETH_IP}/{ETH_PREFIX}", "dev", iface])
    if ok:
        logger.info("Assigned %s/%s to %s", ETH_IP, ETH_PREFIX, iface)
    return ok


def ensure_dnsmasq_installed() -> bool:
    """
    Make sure dnsmasq is available.  If it is not found in PATH and we are root,
    install it using the Linux distribution's package manager. Returns True if
    dnsmasq is available after the attempt.
    """
    if shutil.which("dnsmasq"):
        return True

    if os.geteuid() != 0:
        logger.info("dnsmasq not found and not root — cannot install automatically")
        return False

    installers = [
        ("apt-get", ["apt-get", "install", "-y", "--no-install-recommends", "dnsmasq"]),
        ("dnf", ["dnf", "install", "-y", "dnsmasq"]),
        ("yum", ["yum", "install", "-y", "dnsmasq"]),
        ("zypper", ["zypper", "--non-interactive", "install", "dnsmasq"]),
        ("pacman", ["pacman", "-Sy", "--noconfirm", "dnsmasq"]),
        ("apk", ["apk", "add", "dnsmasq"]),
    ]
    install_cmd = next(
        (cmd for executable, cmd in installers if shutil.which(executable)),
        None,
    )
    if not install_cmd:
        logger.warning(
            "dnsmasq is missing and no supported package manager was found "
            "(apt, dnf, yum, zypper, pacman, or apk)"
        )
        return False

    logger.info(
        "dnsmasq not found — installing with %s (this may take a moment)…",
        install_cmd[0],
    )
    try:
        result = subprocess.run(
            install_cmd,
            capture_output=True,
            timeout=180,
        )
        if result.returncode == 0 and shutil.which("dnsmasq"):
            logger.info("dnsmasq installed successfully")
            return True
        else:
            logger.warning(
                "%s install dnsmasq failed (rc=%d): %s",
                install_cmd[0],
                result.returncode,
                result.stderr.decode(errors="replace"),
            )
    except Exception as exc:
        logger.warning("%s install dnsmasq exception: %s", install_cmd[0], exc)

    return bool(shutil.which("dnsmasq"))


def start_dnsmasq(iface: str) -> bool:
    """
    Ensure dnsmasq is installed, then launch a DHCP-only instance on *iface*.
    Returns True if dnsmasq is running and serving DHCP.

    Strategy to avoid conflicts across Linux distributions:
      • --port=0 disables dnsmasq's DNS listener entirely (no port 53 needed)
        so systemd-resolved can stay running without conflict.
      • We write a minimal config to /tmp/rewind-dnsmasq.conf and pass it with
        -C so our instance is cleanly separated from any system config.
      • We do not stop or disable a system-wide dnsmasq service, because that
        could disrupt unrelated networking on a general-purpose Linux host.
    """
    if not ensure_dnsmasq_installed():
        logger.info("dnsmasq not available — DHCP will not be provided")
        return False

    # Kill only a previous Rewind-Proxy dnsmasq instance.
    _run(["pkill", "-f", "rewind-dnsmasq"])
    time.sleep(0.5)

    # Write a minimal config file for our instance
    conf_path = "/tmp/rewind-dnsmasq.conf"
    conf = (
        f"interface={iface}\n"
        "bind-interfaces\n"
        f"dhcp-range={DHCP_RANGE_START},{DHCP_RANGE_END},255.255.255.0,12h\n"
        f"dhcp-option=option:router,{ETH_IP}\n"
        f"dhcp-option=option:dns-server,8.8.8.8,8.8.4.4\n"
        "port=0\n"              # DHCP only — no DNS listener, no port-53 conflict
        "log-dhcp\n"
        "no-resolv\n"
        "no-poll\n"
    )
    try:
        with open(conf_path, "w") as f:
            f.write(conf)
    except OSError as exc:
        logger.warning("Could not write dnsmasq config: %s", exc)
        conf_path = None

    cmd = ["dnsmasq", "--keep-in-foreground"]
    if conf_path:
        cmd += ["-C", conf_path]
    else:
        cmd += [
            "--interface", iface,
            "--bind-interfaces",
            f"--dhcp-range={DHCP_RANGE_START},{DHCP_RANGE_END},12h",
            f"--dhcp-option=option:router,{ETH_IP}",
            "--dhcp-option=option:dns-server,8.8.8.8",
            "--port=0",
            "--no-resolv",
        ]

    # Launch in background — keep-in-foreground keeps it as our child so we
    # can track/kill it; the monitor thread does not need to wait for it.
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Give it a moment to start; poll() == None means still running
        time.sleep(1.0)
        if proc.poll() is None:
            logger.info(
                "dnsmasq DHCP started on %s (PID %d), range %s–%s",
                iface, proc.pid, DHCP_RANGE_START, DHCP_RANGE_END,
            )
            # Store pid so stop() can clean up
            _state["_dnsmasq_pid"] = proc.pid
            return True
        else:
            logger.warning("dnsmasq exited immediately (rc=%s) — DHCP unavailable", proc.returncode)
            return False
    except Exception as exc:
        logger.warning("Failed to start dnsmasq: %s", exc)
        return False


def enable_ip_forwarding() -> None:
    """Enable IPv4 forwarding on the Linux host."""
    try:
        with open("/proc/sys/net/ipv4/ip_forward", "w") as f:
            f.write("1")
    except OSError as exc:
        logger.warning("Could not enable IP forwarding: %s", exc)


# ──────────────────────────────────────────────
# ARP scanning — find connected devices
# ──────────────────────────────────────────────

def _parse_arp_table(iface: str) -> list[str]:
    """
    Parse /proc/net/arp to find IPv4 addresses reachable via *iface*
    that are on our 192.168.100.x subnet.
    Returns a list of IP address strings.
    """
    devices = []
    try:
        with open("/proc/net/arp") as f:
            for line in f.readlines()[1:]:   # skip header
                parts = line.split()
                if len(parts) < 6:
                    continue
                ip, hw_type, flags, mac, mask, dev = parts[:6]
                if dev != iface:
                    continue
                if mac in ("00:00:00:00:00:00", ""):
                    continue
                if ip.startswith("192.168.100.") and ip != ETH_IP:
                    devices.append(ip)
    except OSError:
        pass
    return devices


def _ping_sweep(iface: str) -> None:
    """Send a ping to each host in the subnet to populate the ARP table."""
    for last_octet in range(2, 20):
        ip = f"192.168.100.{last_octet}"
        try:
            subprocess.run(
                ["ping", "-c1", "-W1", "-I", iface, ip],
                capture_output=True, timeout=2,
            )
        except Exception:
            pass


# ──────────────────────────────────────────────
# Manual-instructions builder
# ──────────────────────────────────────────────

def build_manual_commands(iface: str) -> list[str]:
    return [
        f"sudo ip link set {iface} up",
        f"sudo ip addr add {ETH_IP}/{ETH_PREFIX} dev {iface}",
        "# Install dnsmasq with your Linux distribution's package manager",
        (
            f"sudo dnsmasq --interface {iface} --bind-interfaces --port=0 "
            f"--dhcp-range={DHCP_RANGE_START},{DHCP_RANGE_END},12h "
            f"--dhcp-option=option:router,{ETH_IP} "
            "--dhcp-option=option:dns-server,8.8.8.8 --no-resolv --keep-in-foreground &"
        ),
    ]


# ──────────────────────────────────────────────
# Background monitor thread
# ──────────────────────────────────────────────

def _monitor_loop(iface: str, proxy_port: int) -> None:
    """Continuously monitor the ethernet interface and update _state."""
    is_root       = os.geteuid() == 0
    configured    = False
    dnsmasq_ok    = False
    sweep_done    = False
    last_carrier  = None

    with _lock:
        _state["is_root"]    = is_root
        _state["eth_iface"]  = iface
        _state["proxy_port"] = proxy_port

    logger.info("Linux ethernet monitor started on interface %s (root=%s)", iface, is_root)

    while not _stop_event.is_set():
        carrier = get_carrier_state(iface)

        # ── No cable ────────────────────────────────────────────────
        if not carrier:
            sweep_done  = False
            configured  = False
            dnsmasq_ok  = False
            with _lock:
                _state["status"]          = S_WAITING_CABLE
                _state["eth_ip"]          = None
                _state["old_computer_ip"] = None
                _state["dnsmasq_running"] = False
                _state["manual_cmds"]     = build_manual_commands(iface)
            if last_carrier is not False:
                logger.info("Ethernet: no cable on %s — waiting", iface)
            last_carrier = False
            time.sleep(2)
            continue

        last_carrier = True

        # ── Cable present — configure if needed ─────────────────────
        if not configured:
            with _lock:
                _state["status"] = S_CONFIGURING

            if iface_has_our_ip(iface):
                configured = True
                logger.info("Ethernet %s already has IP %s", iface, ETH_IP)
            elif is_root:
                configured = configure_ethernet(iface)
                if configured and not dnsmasq_ok:
                    dnsmasq_ok = start_dnsmasq(iface)
                    enable_ip_forwarding()
            else:
                # Not root: check if someone assigned the IP manually
                if iface_has_our_ip(iface):
                    configured = True
                else:
                    with _lock:
                        _state["status"]       = S_WAITING_DEVICE
                        _state["eth_ip"]       = None
                        _state["manual_cmds"]  = build_manual_commands(iface)
                    logger.info(
                        "Not root — cannot configure %s automatically. "
                        "Please run the manual commands shown on the home page.", iface
                    )
                    time.sleep(3)
                    continue

        with _lock:
            _state["eth_ip"]          = ETH_IP
            _state["dnsmasq_running"] = dnsmasq_ok
            _state["manual_cmds"]     = [] if is_root else build_manual_commands(iface)

        # ── Scan for connected devices ───────────────────────────────
        if not sweep_done:
            with _lock:
                _state["status"] = S_WAITING_DEVICE
            logger.info("Waiting for old computer to connect on %s …", iface)
            _ping_sweep(iface)
            sweep_done = True

        devices = _parse_arp_table(iface)

        if devices:
            old_ip = devices[0]
            with _lock:
                _state["status"]          = S_CONNECTED
                _state["old_computer_ip"] = old_ip
            logger.info("Old computer detected at %s via %s", old_ip, iface)
        else:
            with _lock:
                _state["status"]          = S_WAITING_DEVICE
                _state["old_computer_ip"] = None

        time.sleep(3)


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────

def get_status() -> dict:
    """Return a copy of the current state (safe to read from any thread)."""
    with _lock:
        return dict(_state)


def start(proxy_port: int = 8080, interface: str | None = None) -> bool:
    """
    Detect Linux, find a safe wired interface, and start the monitor thread.
    Returns True if the Linux ethernet wizard was activated, False otherwise.
    """
    global _monitor_thread

    if not is_linux():
        with _lock:
            _state["status"] = S_NOT_LINUX
        logger.debug("Not running on Linux — skipping ethernet wizard")
        return False

    if not ensure_ip_command():
        with _lock:
            _state["status"] = S_ERROR
            _state["error"] = (
                "The Linux `ip` command is required for automatic ethernet "
                "configuration. Install iproute2 (or iproute) and restart."
            )
        return False

    iface = find_ethernet_interface(interface)
    if not iface:
        default_ifaces = sorted(_default_route_interfaces())
        detail = (
            "No safe wired ethernet interface found. Rewind-Proxy will not "
            "reconfigure an interface carrying the default route."
        )
        if interface:
            detail = (
                f"Ethernet interface '{interface}' is unavailable, wireless, "
                "or carries the default route."
            )
        elif default_ifaces:
            detail += f" Default-route interface(s): {', '.join(default_ifaces)}."
        with _lock:
            _state["status"] = S_ERROR
            _state["error"]  = detail
        logger.warning(detail)
        return False

    logger.info("Linux detected — starting ethernet wizard on %s", iface)

    with _lock:
        _state["status"]     = S_WAITING_CABLE
        _state["eth_iface"]  = iface
        _state["proxy_port"] = proxy_port

    _stop_event.clear()
    _monitor_thread = threading.Thread(
        target=_monitor_loop,
        args=(iface, proxy_port),
        daemon=True,
        name="linux-eth-monitor",
    )
    _monitor_thread.start()
    return True


def stop() -> None:
    """Stop the background monitor thread and any dnsmasq process we started."""
    _stop_event.set()
    if _monitor_thread and _monitor_thread.is_alive():
        _monitor_thread.join(timeout=5)
    # Kill our dnsmasq child process if we spawned one
    pid = _state.get("_dnsmasq_pid")
    if pid:
        try:
            import signal as _signal
            os.kill(pid, _signal.SIGTERM)
            logger.info("Stopped dnsmasq (PID %d)", pid)
        except OSError:
            pass
