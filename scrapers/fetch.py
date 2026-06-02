"""Hardened HTTP fetch layer — the single way anything in this system reaches
the network.

This is security-critical and shared by both the scheduled scrapers and the
on-demand ``scrape_url`` function. Defences against SSRF and resource abuse:

  * https only
  * host must be on the allowlist (scrapers/sources.py)
  * DNS resolved up front; any resolution to a private / loopback / link-local
    / reserved IP is rejected (blocks cloud-metadata 169.254.169.254, localhost,
    RFC1918, etc.)
  * redirects disabled — a 30x to an internal address can't bypass the checks
  * response size capped (streamed, aborted past the limit)
  * connect + read timeout
  * fixed, honest User-Agent

If any check fails we raise FetchError and fetch nothing.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import requests

from .sources import host_is_allowed

USER_AGENT = "rate-tracker/0.1 (+https://github.com/zacharyholt1/rate-tracker)"
DEFAULT_TIMEOUT = (5, 15)          # (connect, read) seconds
MAX_BYTES = 5 * 1024 * 1024        # 5 MB ceiling on any single response


class FetchError(Exception):
    """Raised when a URL is rejected by policy or the fetch fails."""


def _resolved_ips(host: str) -> list[ipaddress._BaseAddress]:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise FetchError(f"DNS resolution failed for {host!r}: {exc}") from exc
    ips = []
    for info in infos:
        addr = info[4][0]
        # Strip IPv6 scope id if present.
        ips.append(ipaddress.ip_address(addr.split("%")[0]))
    return ips


def _assert_public(host: str) -> None:
    """Reject hosts that resolve to any non-public address."""
    for ip in _resolved_ips(host):
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise FetchError(
                f"Refusing to fetch {host!r}: resolves to non-public address {ip}"
            )


def assert_fetchable(url: str) -> str:
    """Validate a URL against all policy checks. Returns the normalised host.
    Raises FetchError on any violation. Exposed so callers (e.g. scrape_url)
    can validate without fetching."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise FetchError(f"Only https is allowed, got {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise FetchError("URL has no host")
    if not host_is_allowed(host):
        raise FetchError(f"Host {host!r} is not on the allowlist")
    _assert_public(host)
    return host


def fetch(url: str, *, timeout=DEFAULT_TIMEOUT, max_bytes=MAX_BYTES) -> bytes:
    """Fetch a URL after passing every policy check. Returns raw bytes.

    Note: we re-validate post-DNS but a fully paranoid implementation would
    also pin the validated IP for the actual connection to defeat DNS-rebinding
    between check and connect. For fetching a fixed allowlist of large public
    institutions that race is not a meaningful threat; documented here so it's
    a conscious decision, not an oversight."""
    assert_fetchable(url)

    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}
    try:
        resp = requests.get(
            url,
            headers=headers,
            timeout=timeout,
            allow_redirects=False,     # a redirect can't smuggle us off-allowlist
            stream=True,
        )
    except requests.RequestException as exc:
        raise FetchError(f"Request failed: {exc}") from exc

    if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
        loc = resp.headers.get("Location", "")
        raise FetchError(f"Redirect not followed ({resp.status_code} -> {loc!r})")
    if resp.status_code != 200:
        raise FetchError(f"HTTP {resp.status_code} for {url}")

    # Stream with a hard byte ceiling so a huge/again response can't OOM us.
    chunks, total = [], 0
    for chunk in resp.iter_content(8192):
        total += len(chunk)
        if total > max_bytes:
            resp.close()
            raise FetchError(f"Response exceeded {max_bytes} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def fetch_text(url: str, **kw) -> str:
    return fetch(url, **kw).decode("utf-8", errors="replace")


def fetch_binary(url: str, **kw) -> bytes:
    return fetch(url, **kw)
