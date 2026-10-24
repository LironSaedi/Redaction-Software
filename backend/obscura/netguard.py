"""Optional hard network block for the whole process (and transcription workers).

Set ``OBSCURA_BLOCK_NET=1`` to make any outbound socket connection raise. Used by the privacy test
suite and recommended on air-gapped servers as a belt-and-braces guard; loopback is still allowed so the
web UI keeps working.
"""
from __future__ import annotations

import os
import socket

_installed = False
_AF_UNIX = getattr(socket, "AF_UNIX", None)  # local sockets; Python on Windows has no AF_UNIX


class NetworkBlocked(RuntimeError):
    pass


def _is_loopback(address) -> bool:
    try:
        host = address[0] if isinstance(address, tuple) else address
    except Exception:
        return False
    return isinstance(host, str) and (host.startswith("127.") or host in ("localhost", "::1", "0.0.0.0"))


def block() -> None:
    global _installed
    if _installed:
        return
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create = socket.create_connection
    real_getaddrinfo = socket.getaddrinfo

    def connect(self, address):
        if self.family == _AF_UNIX or _is_loopback(address):
            return real_connect(self, address)
        raise NetworkBlocked(f"outbound connection blocked: {address!r}")

    def connect_ex(self, address):
        if self.family == _AF_UNIX or _is_loopback(address):
            return real_connect_ex(self, address)
        raise NetworkBlocked(f"outbound connection blocked: {address!r}")

    def create_connection(address, *a, **kw):
        if _is_loopback(address):
            return real_create(address, *a, **kw)
        raise NetworkBlocked(f"outbound connection blocked: {address!r}")

    def getaddrinfo(host, *a, **kw):
        if host in (None, "localhost") or (isinstance(host, str) and (host.startswith("127.") or host == "::1")):
            return real_getaddrinfo(host, *a, **kw)
        raise NetworkBlocked(f"DNS lookup blocked: {host!r}")

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.create_connection = create_connection
    socket.getaddrinfo = getaddrinfo
    _installed = True


def maybe_block() -> None:
    if os.environ.get("OBSCURA_BLOCK_NET") == "1":
        block()
