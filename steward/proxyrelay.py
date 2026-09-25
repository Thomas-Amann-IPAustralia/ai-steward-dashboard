"""A local relay that gives Chrome an authenticated proxy without its password.

Chrome takes its proxy from `--proxy-server`, and a password put there is
visible to every process on the machine (a process's arguments are readable
by any user) and lands in crash logs. It does not even work: Chrome ignores
credentials in that flag, and a headless browser cannot answer the proxy's
407 challenge. So Chrome is pointed at this relay on 127.0.0.1 instead, and
the relay forwards each connection to the real proxy with a
`Proxy-Authorization` header added. The credentials stay inside this Python
process.

It handles what a browser sends a proxy: `CONNECT` for https, after which
bytes are piped untouched, and absolute-form requests for plain http, which
are sent with `Connection: close` so every request gets its own header.
"""

from __future__ import annotations

import base64
import logging
import select
import socket
import socketserver
import threading
from typing import Optional

log = logging.getLogger(__name__)

MAX_HEAD_BYTES = 64 * 1024
IDLE_SECONDS = 120
_HOP_HEADERS = (b"proxy-authorization", b"proxy-connection", b"connection")


class ProxyRelay:
    """Listens on 127.0.0.1 and forwards to an upstream proxy with credentials."""

    def __init__(self, host: str, port: int, user: str, password: str):
        self.upstream = (host, int(port))
        token = base64.b64encode(f"{user}:{password}".encode("utf-8"))
        self._auth = b"Proxy-Authorization: Basic " + token + b"\r\n"
        self._server: Optional[socketserver.ThreadingTCPServer] = None

    def start(self) -> str:
        """Start listening; returns the `host:port` to give Chrome."""
        relay = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self) -> None:
                relay._serve(self.request)

        server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, name="proxy-relay", daemon=True).start()
        self._server = server
        return f"127.0.0.1:{server.server_address[1]}"

    def close(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def _serve(self, client: socket.socket) -> None:
        try:
            head, rest = _read_head(client)
            if head is None:
                return
            with socket.create_connection(self.upstream, timeout=IDLE_SECONDS) as upstream:
                upstream.sendall(self._rewrite(head) + rest)
                _pipe(client, upstream)
        except OSError as exc:
            log.debug("proxy relay connection ended: %s", exc)

    def _rewrite(self, head: bytes) -> bytes:
        """The client's request head with our credentials in place of any it sent."""
        request_line, _, headers = head.partition(b"\r\n")
        tunnel = request_line.upper().startswith(b"CONNECT ")
        kept = [
            line
            for line in headers.split(b"\r\n")
            if line and line.split(b":", 1)[0].strip().lower() not in _HOP_HEADERS
        ]
        out = request_line + b"\r\n" + b"".join(line + b"\r\n" for line in kept) + self._auth
        if not tunnel:
            out += b"Connection: close\r\n"
        return out + b"\r\n"


def _read_head(client: socket.socket) -> tuple[Optional[bytes], bytes]:
    """The request head without its final blank line, and any bytes after it."""
    client.settimeout(IDLE_SECONDS)
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = client.recv(4096)
        if not chunk or len(data) > MAX_HEAD_BYTES:
            return None, b""
        data += chunk
    head, _, rest = data.partition(b"\r\n\r\n")
    return head, rest


def _pipe(a: socket.socket, b: socket.socket) -> None:
    """Copy bytes both ways until either side closes or both go quiet."""
    sockets = [a, b]
    while True:
        readable, _, errored = select.select(sockets, [], sockets, IDLE_SECONDS)
        if errored or not readable:
            return
        for source in readable:
            data = source.recv(65536)
            if not data:
                return
            (b if source is a else a).sendall(data)
