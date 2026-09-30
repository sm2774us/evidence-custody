"""Object storage: write-once originals with retention + legal hold, plus chunk staging.

`FileWormStore` is a reference implementation (read-only mode bits + refuse-overwrite +
sidecar retention). `S3WormStore` maps the same contract onto S3 Object Lock in COMPLIANCE
mode, which even the account root cannot shorten - that is the production control."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, Protocol

from .errors import WormViolation

_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]{0,255}$")


def _safe(key: str) -> str:
    if not _KEY.match(key) or ".." in key.split("/"):
        raise WormViolation("invalid storage key")
    return key


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class ObjectStore(Protocol):
    def put_original(self, key: str, src: Path, sha256: str, retention_until_ms: int) -> str: ...
    def open_original(self, key: str, version_id: str) -> IO[bytes]: ...
    def extend_retention(self, key: str, version_id: str, until_ms: int) -> None: ...
    def set_legal_hold(self, key: str, version_id: str, hold_id: str, on: bool) -> None: ...
    def put_derivative(self, key: str, src: Path) -> None: ...
    def open_derivative(self, key: str) -> IO[bytes]: ...
    def delete(self, key: str) -> None: ...


class FileWormStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        for d in ("originals", "derivatives"):
            (root / d).mkdir(parents=True, exist_ok=True)

    def _p(self, ns: str, key: str) -> Path:
        return self.root / ns / _safe(key)

    def _write_once(self, dst: Path, src: Path) -> bool:
        """Copy src to dst durably; returns False if dst already existed."""
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(f".tmp-{uuid.uuid4().hex}")
        with src.open("rb") as r, tmp.open("wb") as w:
            shutil.copyfileobj(r, w, 1024 * 1024)
            w.flush()
            os.fsync(w.fileno())
        tmp.chmod(0o444)
        try:
            os.link(tmp, dst)  # atomic; fails if dst exists => no overwrite, ever
            created = True
        except FileExistsError:
            created = False
        finally:
            tmp.unlink(missing_ok=True)
        _fsync_dir(dst.parent)
        return created

    @staticmethod
    def _hash_file(p: Path) -> str:
        h = hashlib.sha256()
        with p.open("rb") as f:
            for blk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(blk)
        return h.hexdigest()

    def _meta_path(self, key: str) -> Path:
        p = self._p("originals", key)
        return p.with_name(p.name + ".meta.json")

    def _meta_write(self, key: str, meta: dict[str, Any]) -> None:
        mp = self._meta_path(key)
        tmp = mp.with_name(f".tmp-{uuid.uuid4().hex}")
        tmp.write_text(json.dumps(meta, sort_keys=True))
        tmp.chmod(0o444)
        os.replace(tmp, mp)

    def _meta(self, key: str) -> dict[str, Any]:
        try:
            return json.loads(self._meta_path(key).read_text())  # type: ignore[no-any-return]
        except FileNotFoundError as e:
            raise WormViolation("object not found") from e

    def put_original(self, key: str, src: Path, sha256: str, retention_until_ms: int) -> str:
        dst = self._p("originals", key)
        version = f"v1-{sha256[:16]}"
        if not self._write_once(dst, src):
            if self._hash_file(dst) != sha256:
                raise WormViolation(
                    "refusing to overwrite an existing original with different bytes"
                )
            return version  # idempotent replay of the same commit
        self._meta_write(key, {"sha256": sha256, "retention_until_ms": retention_until_ms,
                               "holds": [], "version_id": version})  # fmt: skip
        return version

    def open_original(self, key: str, version_id: str) -> IO[bytes]:
        return self._p("originals", key).open("rb")

    def extend_retention(self, key: str, version_id: str, until_ms: int) -> None:
        meta = self._meta(key)
        if until_ms < meta["retention_until_ms"]:
            raise WormViolation("retention may only be extended, never shortened")
        meta["retention_until_ms"] = until_ms
        self._meta_write(key, meta)

    def set_legal_hold(self, key: str, version_id: str, hold_id: str, on: bool) -> None:
        meta = self._meta(key)
        holds = set(meta["holds"])
        (holds.add if on else holds.discard)(hold_id)
        meta["holds"] = sorted(holds)
        self._meta_write(key, meta)

    def put_derivative(self, key: str, src: Path) -> None:
        if not self._write_once(self._p("derivatives", key), src):
            raise WormViolation("derivative already exists")

    def open_derivative(self, key: str) -> IO[bytes]:
        return self._p("derivatives", key).open("rb")

    def delete(self, key: str) -> None:
        raise WormViolation(
            "deletion is not supported; disposition is an offline, dual-approved process"
        )


class S3WormStore:  # pragma: no cover - exercised via stubbed client in tests
    """S3 Object Lock (COMPLIANCE) + SSE-KMS + S3-verified SHA-256 on write."""

    def __init__(self, client: Any, bucket: str, kms_key_id: str = "") -> None:
        self.c, self.bucket, self.kms = client, bucket, kms_key_id

    def put_original(self, key: str, src: Path, sha256: str, retention_until_ms: int) -> str:
        args: dict[str, Any] = {
            "Bucket": self.bucket, "Key": f"originals/{_safe(key)}",
            "ChecksumSHA256": base64.b64encode(bytes.fromhex(sha256)).decode(),
            "ObjectLockMode": "COMPLIANCE",
            "ObjectLockRetainUntilDate": datetime.fromtimestamp(retention_until_ms / 1000, UTC),
            "IfNoneMatch": "*",  # write-once at the API level
        }  # fmt: skip
        if self.kms:
            args.update(ServerSideEncryption="aws:kms", SSEKMSKeyId=self.kms)
        with src.open("rb") as f:
            resp = self.c.put_object(Body=f, **args)
        return str(resp["VersionId"])

    def open_original(self, key: str, version_id: str) -> IO[bytes]:
        return self.c.get_object(  # type: ignore[no-any-return]
            Bucket=self.bucket, Key=f"originals/{_safe(key)}", VersionId=version_id
        )["Body"]

    def extend_retention(self, key: str, version_id: str, until_ms: int) -> None:
        self.c.put_object_retention(
            Bucket=self.bucket, Key=f"originals/{_safe(key)}", VersionId=version_id,
            Retention={"Mode": "COMPLIANCE",
                       "RetainUntilDate": datetime.fromtimestamp(until_ms / 1000, UTC)},
        )  # fmt: skip

    def set_legal_hold(self, key: str, version_id: str, hold_id: str, on: bool) -> None:
        self.c.put_object_legal_hold(
            Bucket=self.bucket, Key=f"originals/{_safe(key)}", VersionId=version_id,
            LegalHold={"Status": "ON" if on else "OFF"},
        )  # fmt: skip

    def put_derivative(self, key: str, src: Path) -> None:
        with src.open("rb") as f:
            self.c.put_object(Bucket=self.bucket, Key=f"derivatives/{_safe(key)}", Body=f,
                              IfNoneMatch="*")  # fmt: skip

    def open_derivative(self, key: str) -> IO[bytes]:
        return self.c.get_object(  # type: ignore[no-any-return]
            Bucket=self.bucket, Key=f"derivatives/{_safe(key)}"
        )["Body"]

    def delete(self, key: str) -> None:
        raise WormViolation("deletion is not supported")


class Staging:
    """Untrusted landing zone for chunks. Nothing here is evidence until verified."""

    def __init__(self, root: Path) -> None:
        self.root = root
        (root / "staging").mkdir(parents=True, exist_ok=True)
        (root / "quarantine").mkdir(parents=True, exist_ok=True)

    def _dir(self, session_id: str) -> Path:
        return self.root / "staging" / _safe(session_id)

    def put_chunk(self, session_id: str, idx: int, data: bytes) -> None:
        d = self._dir(session_id)
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f".{idx}.{uuid.uuid4().hex}"
        with tmp.open("wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, d / str(idx))

    def iter_chunks(self, session_id: str, count: int) -> Iterator[bytes]:
        for i in range(count):
            yield (self._dir(session_id) / str(i)).read_bytes()

    def assemble(self, session_id: str, count: int, out: Path) -> None:
        with out.open("wb") as w:
            for blk in self.iter_chunks(session_id, count):
                w.write(blk)
            w.flush()
            os.fsync(w.fileno())

    def quarantine(self, session_id: str) -> Path:
        """Preserve exactly what was received for investigation. Never deleted automatically."""
        dst = self.root / "quarantine" / _safe(session_id)
        if self._dir(session_id).exists() and not dst.exists():
            shutil.move(str(self._dir(session_id)), str(dst))
        return dst

    def cleanup(self, session_id: str) -> None:
        shutil.rmtree(self._dir(session_id), ignore_errors=True)
