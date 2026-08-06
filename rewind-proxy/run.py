#!/usr/bin/env python3
"""
Rewind-Proxy entry point.

Usage:
    python run.py [--host HOST] [--port PORT]

The proxy listens on HOST:PORT (default 0.0.0.0:8080) and routes all HTTP
requests through the Internet Archive Wayback Machine.

To use with an old browser:
    1. In your browser's network/proxy settings, set:
       HTTP Proxy: <this machine's IP address>   Port: 8080
    2. Browse to any http:// URL — it will be served from the archive.
    3. Or open http://<this machine's IP>:8080/ for the Rewind-Proxy home page.
"""

import argparse
import logging
import os
import signal
import socket
import sys

import config
import pi_setup
from proxy import ThreadingHTTPServer, RewindProxyHandler


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
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
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

    # Expose for use by the home page handler
    os.environ["REWIND_PUBLIC_HOME"]   = public_home
    os.environ["REWIND_PROXY_HOST"]    = proxy_host
    os.environ["REWIND_PROXY_PORT"]    = str(proxy_port)
    os.environ["REWIND_NETWORK_NOTE"]  = network_note

    server = ThreadingHTTPServer((args.host, args.port), RewindProxyHandler)

    logger.info("=" * 60)
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

    # Start Raspberry Pi 5 ethernet wizard (no-op on non-Pi hardware)
    pi_active = pi_setup.start(proxy_port=args.port)
    if pi_active:
        logger.info("")
        logger.info("  Raspberry Pi 5 detected!")
        logger.info("  Connect your old computer's ethernet cable to the Pi.")
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
