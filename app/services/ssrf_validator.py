import socket
from ipaddress import ip_address, ip_network
from urllib.parse import urlparse

_PRIVATE_RANGES = [
    ip_network("10.0.0.0/8"),
    ip_network("172.16.0.0/12"),
    ip_network("192.168.0.0/16"),
    ip_network("127.0.0.0/8"),
    ip_network("169.254.0.0/16"),
    ip_network("0.0.0.0/8"),
    ip_network("::1/128"),
    ip_network("fc00::/7"),
    ip_network("fe80::/10"),
]

_BLOCKED_HOSTS = {"localhost", "metadata.google.internal"}


def validate_url_safety(url: str) -> None:
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"URL scheme must be http or https, got '{parsed.scheme}'")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname")

    hostname_lower = hostname.lower().rstrip(".")

    if hostname_lower in _BLOCKED_HOSTS:
        raise ValueError(f"Host '{hostname}' is blocked")

    try:
        resolved_ip = ip_address(socket.gethostbyname(hostname_lower))
    except socket.gaierror:
        raise ValueError(f"Cannot resolve host '{hostname}'")

    for net in _PRIVATE_RANGES:
        if resolved_ip in net:
            raise ValueError(
                f"Host '{hostname}' resolves to {resolved_ip} which is in "
                f"private/reserved range {net}"
            )
