"""Configure a fresh standalone exam LAN .env; never touches Docker or EC2."""
import argparse
from ipaddress import IPv4Address, ip_address
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def lan_ip(value):
    try:
        address = ip_address(value)
    except ValueError:
        raise ValueError("Enter the LAN server IPv4 address, e.g. 192.168.1.20") from None
    if (not isinstance(address, IPv4Address) or not address.is_private
            or address.is_loopback or address.is_link_local
            or address.is_multicast or address.is_unspecified):
        raise ValueError("Use a real private LAN IPv4 address of this machine")
    return str(address)


def setting(content, key):
    matched = re.search(r"^" + re.escape(key) + r"=(.*)$", content, re.M)
    return matched.group(1).strip() if matched else ""


def put(content, key, value):
    if any(ch in value for ch in "\r\n"):
        raise ValueError("Newlines are not allowed in configuration values")
    pattern = r"^" + re.escape(key) + r"=.*$"
    line = key + "=" + value
    if re.search(pattern, content, re.M):
        return re.sub(pattern, lambda _: line, content, count=1, flags=re.M)
    return content.rstrip() + "\n" + line + "\n"


def prepare(content, ip):
    ip = lan_ip(ip)
    previous = setting(content, "ARENA_PUBLIC_DOMAIN")
    if previous and previous != ip:
        raise ValueError("Existing .env uses another host/domain; review it manually before changing a deployed installation")
    previous_bind = setting(content, "ARENA_LAN_BIND_IP")
    if previous_bind and previous_bind != ip:
        raise ValueError("Existing .env binds a different LAN interface; review it manually")
    secret = setting(content, "ARENA_PROXY_SECRET")
    if secret and len(secret) < 48:
        raise ValueError("Existing proxy secret is too short; replace it privately")
    if not secret:
        secret = secrets.token_urlsafe(48)
    for key, value in (
        ("ARENA_PUBLIC_DOMAIN", ip),
        ("ARENA_LAN_BIND_IP", ip),
        ("ARENA_PROXY_SECRET", secret),
    ):
        content = put(content, key, value)
    return content


def main(argv=None):
    parser = argparse.ArgumentParser(description="One-time exam LAN setup; only writes private .env")
    parser.add_argument("--ip", required=True, help="LAN IPv4 of this PC/server, e.g. 192.168.1.20")
    args = parser.parse_args(argv)
    try:
        ip = lan_ip(args.ip)
        subprocess.run([sys.executable, str(ROOT / "scripts" / "configure_sandbox.py")],
                       cwd=ROOT, check=True)
        target = ROOT / ".env"
        content = prepare(target.read_text(encoding="utf-8"), ip)
        target.write_text(content, encoding="utf-8", newline="\n")
        if os.name != "nt":
            target.chmod(0o600)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"LAN setup refused: {exc}\n")
    print(f"LAN configuration ready for https://{ip}")
    print("Next: build, create Admin and trust the Caddy local CA on student PCs.")
    print("No Internet/network isolation was configured by this script.")


if __name__ == "__main__":
    main()
