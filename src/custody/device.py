"""Body-camera side: device identity and signed capture manifests (reference/simulator)."""

from __future__ import annotations

import hashlib
import math
import secrets
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .crypto import canonical_json


class DeviceIdentity:
    """In firmware this key lives in a secure element; it never leaves the camera."""

    def __init__(
        self, device_id: str, officer_id: str, agency_id: str, seed_hex: str | None = None
    ) -> None:
        self.device_id, self.officer_id, self.agency_id = device_id, officer_id, agency_id
        self._key = Ed25519PrivateKey.from_private_bytes(
            bytes.fromhex(seed_hex or secrets.token_hex(32))
        )
        self.public_hex = (
            self._key.public_key()
            .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
            .hex()
        )

    def sign(self, message: bytes) -> str:
        return self._key.sign(message).hex()


class ChunkSource:
    """Random-access chunk reader over bytes or a file, so huge files never load into memory."""

    def __init__(self, data: bytes | Path, chunk_size: int) -> None:
        self.data, self.chunk_size = data, chunk_size
        self.size = len(data) if isinstance(data, bytes) else data.stat().st_size

    @property
    def count(self) -> int:
        return math.ceil(self.size / self.chunk_size)

    def read(self, idx: int) -> bytes:
        off = idx * self.chunk_size
        if isinstance(self.data, bytes):
            return self.data[off : off + self.chunk_size]
        with self.data.open("rb") as f:
            f.seek(off)
            return f.read(self.chunk_size)

    def full_sha256(self) -> str:
        h = hashlib.sha256()
        for i in range(self.count):
            h.update(self.read(i))
        return h.hexdigest()


def build_manifest(identity: DeviceIdentity, src: ChunkSource, *, sequence_no: int,
                   case_id: str | None = None, media_type: str = "video/mp4",
                   retention_class: str = "standard", idempotency_key: str | None = None,
                   captured_at_ms: int | None = None,
                   full_sha256: str | None = None) -> tuple[dict[str, Any], str]:  # fmt: skip
    manifest = {
        "schema_version": 1,
        "idempotency_key": idempotency_key or secrets.token_urlsafe(24),
        "device_id": identity.device_id, "officer_id": identity.officer_id,
        "agency_id": identity.agency_id, "case_id": case_id, "sequence_no": sequence_no,
        "captured_at_ms": captured_at_ms if captured_at_ms is not None else int(time.time() * 1000),
        "media_type": media_type, "size": src.size, "chunk_size": src.chunk_size,
        "chunk_sha256": [hashlib.sha256(src.read(i)).hexdigest() for i in range(src.count)],
        "sha256": full_sha256 or src.full_sha256(), "retention_class": retention_class,
    }  # fmt: skip
    return manifest, identity.sign(canonical_json(manifest))


FaultHook = Callable[[int, int, bytes], bytes | None]
