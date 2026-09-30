"""Resumable, idempotent uploader with retry/backoff and receipt verification."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from .crypto import canonical_json, verify_signature
from .device import ChunkSource, DeviceIdentity, FaultHook, build_manifest


class UploadError(Exception):
    def __init__(self, message: str, status: int = 0, body: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status, self.body = status, body or {}


class UploadClient:
    def __init__(self, http: httpx.Client, token: str, identity: DeviceIdentity,
                 service_public_key: str | None = None, max_retries: int = 6,
                 sleep: Callable[[float], None] = time.sleep,
                 fault: FaultHook | None = None) -> None:  # fmt: skip
        self.http, self.token, self.id = http, token, identity
        self.pub, self.max_retries, self.sleep, self.fault = (
            service_public_key,
            max_retries,
            sleep,
            fault,
        )
        self.stats = {"retries": 0, "resent_chunks": 0}

    def _call(self, method: str, url: str, **kw: Any) -> httpx.Response:
        headers = {"authorization": f"Bearer {self.token}", **kw.pop("headers", {})}
        for attempt in range(self.max_retries + 1):
            try:
                r = self.http.request(method, url, headers=headers, **kw)
            except httpx.TransportError:
                r = None
            if r is not None and r.status_code < 500:
                return r
            if attempt == self.max_retries:
                raise UploadError("service unavailable after retries", r.status_code if r else 0)
            self.stats["retries"] += 1
            self.sleep(min(30.0, 0.25 * 2**attempt) * (0.5 + random.random() / 2))  # noqa: S311
        raise AssertionError("unreachable")  # pragma: no cover

    def _service_key(self) -> str:
        if not self.pub:
            self.pub = self.http.get("/v1/keys").json()["public_key"]  # pin this in production
        return str(self.pub)

    def upload(self, data: bytes | Path, *, sequence_no: int, chunk_size: int = 1024 * 1024,
               case_id: str | None = None, media_type: str = "video/mp4",
               retention_class: str = "standard", idempotency_key: str | None = None,
               captured_at_ms: int | None = None,
               full_sha256: str | None = None) -> dict[str, Any]:  # fmt: skip
        src = ChunkSource(data, chunk_size)
        manifest, sig = build_manifest(self.id, src, sequence_no=sequence_no, case_id=case_id,
                                       media_type=media_type, retention_class=retention_class,
                                       idempotency_key=idempotency_key, captured_at_ms=captured_at_ms,
                                       full_sha256=full_sha256)  # fmt: skip
        r = self._call("POST", "/v1/uploads", json={"manifest": manifest, "signature": sig})
        if r.status_code not in (200, 201):
            raise UploadError("create failed", r.status_code, r.json())
        sess = r.json()
        sid = sess["session_id"]
        if sess["state"] == "available":
            return self._finish(sid, manifest)
        # Resume: ask the server what it already has (works after crash/power loss/reboot).
        missing = self._call("GET", f"/v1/uploads/{sid}").json()["missing_chunks"]
        for idx in missing:
            self._send_chunk(sid, idx, src.read(idx))
        return self._finish(sid, manifest)

    def _send_chunk(self, sid: str, idx: int, data: bytes) -> None:
        for attempt in range(self.max_retries + 1):
            payload: bytes | None = self.fault(idx, attempt, data) if self.fault else data
            if payload is None:  # simulated connectivity loss
                self.stats["retries"] += 1
                continue
            r = self._call("PUT", f"/v1/uploads/{sid}/chunks/{idx}", content=payload)
            if r.status_code == 200:
                return
            body = r.json()
            if r.status_code == 422 and body.get("retryable"):
                self.stats["resent_chunks"] += 1
                continue
            raise UploadError("chunk rejected", r.status_code, body)
        raise UploadError(f"chunk {idx} failed after retries")

    def _finish(self, sid: str, manifest: dict[str, Any]) -> dict[str, Any]:
        r = self._call("POST", f"/v1/uploads/{sid}/complete")
        if r.status_code not in (200, 201):
            raise UploadError("upload not acknowledged", r.status_code, r.json())
        body = r.json()
        rec = body["receipt"]
        if not verify_signature(self._service_key(), body["signature"], canonical_json(rec)):
            raise UploadError("receipt signature invalid")
        if rec["sha256"] != manifest["sha256"] or rec["size"] != manifest["size"]:
            raise UploadError("receipt does not match local capture")
        result: dict[str, Any] = body
        return result  # only now may the camera mark the local copy as safe to purge
