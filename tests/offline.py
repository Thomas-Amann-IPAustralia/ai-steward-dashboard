"""The tests run without a network, and this makes sure of it.

Any DNS lookup or connection to somewhere other than this machine fails the
test that made it, so a stub that stops matching the code it stands in for
shows up as an error instead of quietly reaching the internet.
"""

import socket

_LOCAL = {"localhost", "127.0.0.1", "::1"}
_getaddrinfo = socket.getaddrinfo
_connect = socket.socket.connect


class NetworkUsed(RuntimeError):
    pass


def _guarded_getaddrinfo(host, *args, **kwargs):
    if host not in _LOCAL:
        raise NetworkUsed(f"a test looked up {host!r}; stub the network instead")
    return _getaddrinfo(host, *args, **kwargs)


def _guarded_connect(sock, address):
    host = address[0] if isinstance(address, tuple) else address
    if host not in _LOCAL:
        raise NetworkUsed(f"a test connected to {address!r}; stub the network instead")
    return _connect(sock, address)


socket.getaddrinfo = _guarded_getaddrinfo
socket.socket.connect = _guarded_connect
