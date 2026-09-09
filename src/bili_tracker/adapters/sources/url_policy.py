from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import ParseResult, urljoin, urlparse


class UrlPolicyError(ValueError):
    code = "source.url_not_allowed"


def _is_public_host(hostname: str) -> bool:
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return hostname.lower() not in {"localhost", "localhost.localdomain"}
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


@dataclass(frozen=True)
class UrlPolicy:
    allowed_hosts: frozenset[str] = frozenset()
    resolve_dns: bool = False
    max_redirects: int = 3

    def validate(self, value: str, *, allowed_hosts: frozenset[str] | None = None) -> ParseResult:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise UrlPolicyError("only http and https URLs are accepted")
        if parsed.username or parsed.password:
            raise UrlPolicyError("URL credentials are not accepted")
        hostname = parsed.hostname.lower().rstrip(".")
        hosts = allowed_hosts if allowed_hosts is not None else self.allowed_hosts
        if hosts and not any(hostname == host or hostname.endswith("." + host) for host in hosts):
            raise UrlPolicyError("URL host is not supported")
        if not _is_public_host(hostname):
            raise UrlPolicyError("private and local network addresses are not accepted")
        if self.resolve_dns:
            try:
                addresses = {
                    item[4][0]
                    for item in socket.getaddrinfo(hostname, parsed.port, type=socket.SOCK_STREAM)
                }
            except OSError as exc:
                raise UrlPolicyError("URL host could not be resolved") from exc
            if not addresses or any(not _is_public_host(address) for address in addresses):
                raise UrlPolicyError("URL host resolves to a private address")
        return parsed

    def redirect(
        self, current: str, location: str, *, allowed_hosts: frozenset[str] | None = None
    ) -> str:
        target = urljoin(current, location)
        self.validate(target, allowed_hosts=allowed_hosts)
        return target
