"""LAN by default; named/public hosts require an explicit read-only deployment."""
from dataclasses import dataclass
from ipaddress import ip_address, ip_network
from urllib.parse import urlparse
import os
import socket

PRIVATE_V4 = tuple(ip_network(net) for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def parse_host(value: str):
    parsed = urlparse("http://" + value)
    if (not parsed.hostname or parsed.username is not None or parsed.password is not None
            or parsed.path or parsed.query or parsed.fragment or any(c.isspace() for c in value)):
        raise ValueError("Invalid Host")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("Invalid port")
    return parsed


def demo_host(host_header: str) -> bool:
    try:
        hostname = parse_host(host_header).hostname
        if hostname in {"localhost", "testserver"}:
            return True
        address = ip_address(hostname or "")
        return (address.is_loopback or address.is_link_local
                or (address.version == 4 and any(address in net for net in PRIVATE_V4))
                or (address.version == 6 and address in ip_network("fc00::/7")))
    except ValueError:
        return False


def same_origin(origin: str | None, host: str, scheme: str | None = None) -> bool:
    if not origin:
        return True  # CLI/test clients don't send Origin.
    try:
        parsed = urlparse(origin)
        expected = parse_host(host)
        actual_scheme = {"ws": "http", "wss": "https"}.get(scheme, scheme)
        if parsed.scheme not in ("http", "https") or (actual_scheme and parsed.scheme != actual_scheme):
            return False
        if parsed.username is not None or parsed.password is not None or parsed.path or parsed.query or parsed.fragment:
            return False
        default_port = 443 if parsed.scheme == "https" else 80
        return (parsed.hostname == expected.hostname
                and (parsed.port or default_port) == (expected.port or default_port))
    except ValueError:
        return False


@dataclass(frozen=True)
class NetworkSettings:
    read_only: bool = False
    allowed_hosts: tuple[str, ...] = ()
    public_gateway: bool = False

    def __post_init__(self):
        if type(self.public_gateway) is not bool or (self.public_gateway and self.read_only):
            raise ValueError("Invalid Public Gateway network mode")
        if self.public_gateway and not self.allowed_hosts:
            raise ValueError("Public Gateway requires explicit hosts")
        for host in self.allowed_hosts:
            parsed = parse_host(host)
            if parsed.port is not None or "*" in host:
                raise ValueError("ARENA_ALLOWED_HOSTS: use exact hostnames without ports or wildcards.")
            if not demo_host(host) and not (self.read_only or self.public_gateway):
                raise ValueError("Named/public hosts require read-only or explicit Public Gateway mode")

    @classmethod
    def from_environment(cls):
        mode = os.environ.get("ARENA_READ_ONLY", "0").strip().lower()
        if mode not in {"0", "1", "false", "true"}:
            raise ValueError("ARENA_READ_ONLY must be 0 or 1.")
        hosts = tuple(h.strip().lower() for h in os.environ.get("ARENA_ALLOWED_HOSTS", "").split(",") if h.strip())
        gateway = os.environ.get("ARENA_PUBLIC_GATEWAY", "0").strip().lower()
        if gateway not in {"0", "1", "false", "true"}:
            raise ValueError("ARENA_PUBLIC_GATEWAY must be 0 or 1")
        return cls(mode in {"1", "true"}, hosts, gateway in {"1", "true"})

    def allows_host(self, host: str) -> bool:
        try:
            return demo_host(host) or parse_host(host).hostname in self.allowed_hosts
        except ValueError:
            return False


def lan_addresses() -> list[str]:
    try:
        values = {info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
        return sorted(address for address in values if demo_host(address) and not ip_address(address).is_loopback)
    except OSError:
        return []
