"""Process-local fail-closed network sentinel for C0A dry runs."""

from __future__ import annotations

from contextlib import AbstractContextManager
import socket
import threading
from typing import Any


class CanaryNetworkBlocked(OSError):
    def __init__(self) -> None:
        super().__init__("c0a_external_network_blocked")
        self.reason_code = "c0a_external_network_blocked"


class FailClosedNetworkSentinel(AbstractContextManager):
    """Blocks DNS and socket connection entry points and restores them exactly."""

    def __init__(self) -> None:
        self._originals: dict[tuple[Any, str], Any] = {}
        self._lock = threading.Lock()
        self.network_call_count = 0

    def _blocked(self, *args, **kwargs):
        with self._lock:
            self.network_call_count += 1
        raise CanaryNetworkBlocked()

    def __enter__(self) -> "FailClosedNetworkSentinel":
        targets = [
            (socket, "create_connection"), (socket, "getaddrinfo"),
            (socket, "gethostbyname"), (socket, "gethostbyname_ex"),
            (socket, "gethostbyaddr"), (socket, "getnameinfo"),
            (socket.socket, "connect"), (socket.socket, "connect_ex"),
            (socket.socket, "send"), (socket.socket, "sendall"),
            (socket.socket, "sendto"),
        ]
        for owner, name in targets:
            self._originals[(owner, name)] = getattr(owner, name)
            setattr(owner, name, self._blocked)
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        for (owner, name), original in reversed(list(self._originals.items())):
            setattr(owner, name, original)
        self._originals.clear()
        return False
