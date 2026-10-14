#!/usr/bin/env python3
"""
Rewind-Proxy entry point.

Usage:
    python run.py [--host HOST] [--port PORT] [--headless] [--debug]

The proxy listens on HOST:PORT (default 0.0.0.0:8080) and routes all HTTP
requests through the Internet Archive Wayback Machine.

Normal mode:
    - Home page with URL form and quick links served at /
    - /go, /r, and /setup pages available
    - Configure browser proxy settings OR open the home page directly

Headless mode (--headless):
    - No web UI (home page, quick links, setup page replaced with plain-text status)
    - Full proxy functionality still active: browser proxy settings work as normal
    - Useful for running as a background service on a Linux host where no one will
      open the home page directly
"""

import argparse
import logging
import os
import signal
import socket
import sys

import config
import pi_setup

try:
    from proxy import ThreadingHTTPServer, RewindProxyHandler
except ModuleNotFoundError as exc:
    project_dir = os.path.dirname(os.path.abspath(__file__))
    venv_python = os.path.join(project_dir, "venv", "bin", "python")
    missing = exc.name or "unknown"
    print(
        "\nRewind-Proxy cannot start because a required Python package is missing:\n"
        f"  {missing}\n\n"
        "Run the setup script, then start Rewind-Proxy with its virtual environment:\n\n"
        f"  cd {project_dir}\n"
        "  chmod +x setup.sh\n"
        "  ./setup.sh\n"
        f"  sudo {venv_python} run.py\n\n"
        "Do not use the system 'python' or 'python3' command unless you installed\n"
        "requirements.txt into that same interpreter.\n",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc


def _local_ip() -> str:
    """Best-effort: return the machine's LAN IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def main():
    parser = argparse.ArgumentParser(description="Rewind-Proxy: browse the Wayback Machine")
    parser.add_argument("--host", default=config.PROXY_HOST, help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=config.PROXY_PORT, help="Port to listen on (default: 8080)")
    parser.add_argument(
        "--interface",
        metavar="NAME",
        help=(
            "Wired Linux interface to use for the old computer (for example eth0 "
            "or enp3s0). By default Rewind-Proxy selects a safe non-default-route "
            "Ethernet interface automatically."
        ),
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--headless",
        action="store_true",
        help=(
            "Headless mode: disable the web UI (home page, quick links, setup page). "
            "The proxy itself still works — configure your browser's HTTP proxy settings "
            "to point here and browse normally. Useful for background/service deployments."
        ),
    )
    args = parser.parse_args()

    log_level = logging.DEBUG if args.debug else getattr(logging, config.LOG_LEVEL)
    logging.basicConfig(level=log_level, format=config.LOG_FORMAT)
    logger = logging.getLogger(__name__)

    # Detect the public URL (Replit cloud env or plain LAN)
    replit_domain = os.environ.get("REPLIT_DEV_DOMAIN", "")
    if replit_domain:
        public_home   = f"https://{replit_domain}:{args.port}/"
        proxy_host    = replit_domain
        proxy_port    = args.port
        network_note  = "(Replit cloud — accessible from any browser)"
    else:
        local_ip      = _local_ip()
        public_home   = f"http://{local_ip}:{args.port}/"
        proxy_host    = local_ip
        proxy_port    = args.port
        network_note  = "(local network — make sure port is not firewalled)"

    # Expose for use by the request handler
    os.environ["REWIND_PUBLIC_HOME"]   = public_home
    os.environ["REWIND_PROXY_HOST"]    = proxy_host
    os.environ["REWIND_PROXY_PORT"]    = str(proxy_port)
    os.environ["REWIND_NETWORK_NOTE"]  = network_note
    os.environ["REWIND_HEADLESS"]      = "1" if args.headless else "0"

    server = ThreadingHTTPServer((args.host, args.port), RewindProxyHandler)

    logger.info("=" * 60)
    if args.headless:
        logger.info("  Rewind-Proxy started  [HEADLESS]  %s", network_note)
        logger.info("")
        logger.info("  Web UI disabled. Configure your browser's proxy settings:")
        logger.info("  Proxy host : %s", proxy_host)
        logger.info("  Proxy port : %d", proxy_port)
        logger.info("  Then browse any http:// URL normally.")
        logger.info("")
        logger.info("  Status endpoint: %s", public_home)
    else:
        logger.info("  Rewind-Proxy started  %s", network_note)
        logger.info("")
        logger.info("  Open this URL in any browser:")
        logger.info("  >>> %s <<<", public_home)
        logger.info("")
        logger.info("  — OR — configure your old browser's proxy settings:")
        logger.info("  Proxy host : %s", proxy_host)
        logger.info("  Proxy port : %d", proxy_port)
        logger.info("  Then browse any http:// URL normally.")
    logger.info("=" * 60)

    # Start Linux ethernet wizard (no-op on non-Linux systems).
    ethernet_active = pi_setup.start(
        proxy_port=args.port,
        interface=args.interface,
    )
    if ethernet_active:
        ethernet_status = pi_setup.get_status()
        ethernet_iface = ethernet_status.get("eth_iface", "unknown")
        logger.info("")
        logger.info("  Linux ethernet setup enabled on %s.", ethernet_iface)
        logger.info("  Connect your old computer to that ethernet port.")
        if not args.headless:
            logger.info("  The home page will show live setup instructions.")
        logger.info("=" * 60)

    def shutdown(signum, frame):
        logger.info("Shutting down Rewind-Proxy...")
        pi_setup.stop()
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Interrupted — shutting down.")
        pi_setup.stop()
        server.shutdown()


if __name__ == "__main__":
    main()
