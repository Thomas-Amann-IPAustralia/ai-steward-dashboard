"""Requests to places the pipeline did not choose, and error text safe to publish.

Most of what the pipeline fetches is decided by someone else: the DTA's
register lists the transparency statements, a monitored site decides where
its redirects go, a feed decides what it links to. Three rules apply to every
request, whoever chose the destination:

* **Only public addresses.** A destination (including every redirect hop)
  whose host resolves to a loopback, private, link-local or otherwise
  non-public address is refused before a connection is made. Whatever such a
  request returned would otherwise be committed to a public repository.
* **A size cap.** Bodies are streamed and abandoned once they pass the cap,
  measured after decompression, so a hostile or broken endpoint cannot
  exhaust the runner's memory.
* **Error text is scrubbed.** Failure messages end up in hashes.json,
  health.json and transparency/statements.json, which are published. They
  are stripped of credentials and proxy details and kept short.
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
import time
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests

MAX_REDIRECTS = 10
CHUNK_BYTES = 64 * 1024
# requests' timeout bounds each wait, not the whole body; a server sending a
# byte just inside it every time would never time out. The body gets this
# many timeouts' worth in total, and never less than a minute.
BODY_TIMEOUTS = 3
MIN_BODY_SECONDS = 60
MAX_ERROR_CHARS = 240

# Environment values that must never appear in published text.
_SECRET_ENV = ("PROXY_PASS", "PROXY_USER", "PROXY_HOST", "GEMINI_API_KEY")
_CREDENTIALS_IN_URL = re.compile(r"(?<=://)[^/\s@]+@")


class UnsafeDestination(requests.RequestException):
    """The URL is not an http(s) URL on a public address."""


class ResponseTooLarge(requests.RequestException):
    """The body passed the size cap."""


def is_public_host(host: str) -> bool:
    """Whether every address the host resolves to is publicly routable.

    A name that does not resolve here is allowed through: the request will
    fail on its own, or, through a proxy, resolve on the proxy's network,
    which is not the runner's.
    """
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        return True
    for info in infos:
        address = str(info[4][0]).split("%", 1)[0]
        try:
            if not ipaddress.ip_address(address).is_global:
                return False
        except ValueError:
            return False
    return True


def check_destination(url: str) -> None:
    """Raise UnsafeDestination unless the URL is http(s) on a public host."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise UnsafeDestination(f"refused {parsed.scheme or 'schemeless'} URL")
    if not is_public_host(parsed.hostname):
        raise UnsafeDestination(f"refused {parsed.hostname}: not a public address")


def is_allowed_destination(url: str) -> bool:
    try:
        check_destination(url)
    except UnsafeDestination:
        return False
    return True


def request(
    method: str,
    url: str,
    *,
    max_bytes: int,
    timeout: float,
    headers: Optional[dict] = None,
    params: Optional[dict] = None,
    json: Optional[dict] = None,
    proxies: Optional[dict] = None,
) -> requests.Response:
    """A request whose destination and every redirect hop are checked first,
    and whose body is read in full up to `max_bytes`.

    Redirects are followed here rather than by requests so each hop can be
    checked before it is connected to. Raises a requests.RequestException
    subclass on any failure, as requests itself does.
    """
    with requests.Session() as session:
        for _ in range(MAX_REDIRECTS + 1):
            check_destination(url)
            response = session.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json,
                timeout=timeout,
                proxies=proxies,
                allow_redirects=False,
                stream=True,
            )
            if not response.is_redirect:
                _read_capped(response, max_bytes, max(MIN_BODY_SECONDS, timeout * BODY_TIMEOUTS))
                return response
            response.close()
            url = urljoin(response.url, response.headers["location"])
            params = None  # carried in the redirected URL
            if response.status_code == 303 or (response.status_code in (301, 302) and method == "POST"):
                method, json = "GET", None
    raise requests.TooManyRedirects(f"more than {MAX_REDIRECTS} redirects")


def get(url: str, **kwargs) -> requests.Response:
    return request("GET", url, **kwargs)


def post(url: str, **kwargs) -> requests.Response:
    return request("POST", url, **kwargs)


def _read_capped(response: requests.Response, max_bytes: int, max_seconds: float) -> None:
    deadline = time.monotonic() + max_seconds
    declared = response.headers.get("Content-Length", "")
    if declared.isdigit() and int(declared) > max_bytes:
        response.close()
        raise ResponseTooLarge(f"response declares {int(declared):,} bytes, over the {max_bytes:,} byte limit")
    chunks, total = [], 0
    for chunk in response.iter_content(CHUNK_BYTES):
        total += len(chunk)
        if total > max_bytes:
            response.close()
            raise ResponseTooLarge(f"response passed the {max_bytes:,} byte limit")
        if time.monotonic() > deadline:
            response.close()
            raise requests.Timeout(f"body still arriving after {max_seconds:.0f}s")
        chunks.append(chunk)
    # requests keeps the body here once read; setting it makes .content,
    # .text and .json() work as they would without streaming.
    response._content = b"".join(chunks)


# --- Error text --------------------------------------------------------------------


def scrub_error(text: str) -> str:
    """Error text that is safe to publish.

    Removes credentials embedded in URLs and the values of the proxy and API
    secrets, collapses whitespace and bounds the length.
    """
    text = _CREDENTIALS_IN_URL.sub("***@", text or "")
    for name in _SECRET_ENV:
        value = os.environ.get(name) or ""
        if len(value) >= 4:
            text = text.replace(value, "***")
    text = " ".join(text.split())
    if len(text) > MAX_ERROR_CHARS:
        text = text[: MAX_ERROR_CHARS - 1].rstrip() + "…"
    return text


def describe_error(exc: BaseException) -> str:
    """`Type: message` for an exception, scrubbed for publishing."""
    message = str(exc)
    return scrub_error(f"{type(exc).__name__}: {message}" if message else type(exc).__name__)
