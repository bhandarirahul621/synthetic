"""File storage for uploads and generated datasets.

:class:`BlobStore` is the interface; :class:`LocalBlobStore` keeps files
under ``var/blobs``. An S3 implementation can replace it later (signed URLs,
server-side encryption) without changing the routes or the job runner.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import BinaryIO, Protocol

_SAFE_KEY = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*$")


class BlobStore(Protocol):
    """What the API needs from an object store."""

    def write(self, key: str, stream: BinaryIO, max_bytes: int | None = None) -> int: ...
    def put_file(self, key: str, source: Path) -> int: ...
    def put_bytes(self, key: str, data: bytes) -> int: ...
    def local_path(self, key: str) -> Path: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...
    def delete_prefix(self, prefix: str) -> None: ...


class BlobTooLarge(Exception):
    """Raised when a streamed upload exceeds the size limit."""


class LocalBlobStore:
    """Blob store on the local disk. Keys look like ``uploads/ws_x/upl_y/file.csv``."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if not _SAFE_KEY.match(key) or ".." in key.split("/"):
            raise ValueError("invalid blob key")
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError("invalid blob key")
        return path

    def write(self, key: str, stream: BinaryIO, max_bytes: int | None = None) -> int:
        """Copy a stream to ``key`` in 1 MB chunks; enforce ``max_bytes``."""
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        total = 0
        try:
            with path.open("wb") as fh:
                while chunk := stream.read(1 << 20):
                    total += len(chunk)
                    if max_bytes is not None and total > max_bytes:
                        raise BlobTooLarge()
                    fh.write(chunk)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return total

    def put_file(self, key: str, source: Path) -> int:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, path)
        return path.stat().st_size

    def put_bytes(self, key: str, data: bytes) -> int:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return len(data)

    def local_path(self, key: str) -> Path:
        return self._path(key)

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def delete_prefix(self, prefix: str) -> None:
        path = self._path(prefix.rstrip("/"))
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink()
