"""Publish completed output without truncating an existing destination."""
from pathlib import Path
import os
import tempfile


def atomic_write_bytes(destination: Path, data: bytes) -> None:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp",
                                     dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            if stream.write(data) != len(data):
                raise OSError("Incomplete XML write")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
