"""Same-origin LAN demo access; no global public host support or CORS wildcard."""
from ipaddress import ip_address, ip_network
from urllib.parse import urlparse
import socket

PRIVATE_V4 = tuple(ip_network(net) for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def demo_host(host_header: str) -> bool:
    try:
        hostname = urlparse("http://" + host_header).hostname
        if hostname in {"localhost", "testserver"}:
            return True
        address = ip_address(hostname or "")
        return (address.is_loopback or address.is_link_local
                or (address.version == 4 and any(address in net for net in PRIVATE_V4))
                or (address.version == 6 and address in ip_network("fc00::/7")))
    except ValueError:
        return False


def same_origin(origin: str | None, host: str) -> bool:
    if not origin:
        return True  # CLI/test clients don't send Origin.
    parsed = urlparse(origin)
    return parsed.scheme in ("http", "https") and parsed.netloc.lower() == host.lower()


def lan_addresses() -> list[str]:
    try:
        values = {info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
        return sorted(address for address in values if demo_host(address) and not ip_address(address).is_loopback)
    except OSError:
        return []
