"""Global test fixtures and environment configuration."""

from __future__ import annotations

import os
import socket
from pathlib import Path
import pytest

# Ensure headless offscreen platform for Qt widgets by default
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def deny_external_network(monkeypatch, request):
    """Guard tests against unintended external network calls.

    Allows loopback (localhost/127.0.0.1) for local inter-thread/Qt IPC,
    but blocks all outbound traffic to public networks.
    """
    if "allow_network" in request.keywords:
        return

    real_connect = socket.socket.connect

    def guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) and address else address
        allowed = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}
        if str(host) not in allowed and not str(host).startswith("127."):
            raise RuntimeError(
                f"Network connection denied to {address}. "
                "Tests must mock external network services."
            )
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
