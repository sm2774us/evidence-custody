"""End-to-end simulation: flaky network, corruption, replay, tamper, then a custody report."""

from __future__ import annotations

import contextlib
import hashlib
import os
import random
import secrets
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast

import httpx
from fastapi.testclient import TestClient

from .app import create_app
from .auth import Role, issue_token
from .client import UploadClient, UploadError
from .config import Settings
from .device import DeviceIdentity


def run_demo() -> int:
    with tempfile.TemporaryDirectory() as td:
        s = Settings(data_dir=Path(td)).with_dev_secrets()
        app = create_app(s)
        svc = app.state.svc
        http = cast(httpx.Client, TestClient(app))

        def tok(sub: str, role: str) -> str:
            return issue_token(s.token_secret, sub, Role(role), "agency-1", svc.clock(), 3600)

        def h(t: str) -> dict[str, str]:
            return {"authorization": f"Bearer {t}"}

        cam = DeviceIdentity("cam-0001", "officer-77", "agency-1")
        http.post("/v1/devices", headers=h(tok("admin-a", "admin")), json={
            "device_id": cam.device_id, "public_key": cam.public_hex,
            "officer_id": cam.officer_id, "agency_id": "agency-1"})  # fmt: skip
        http.post(f"/v1/devices/{cam.device_id}/activate", headers=h(tok("admin-b", "admin")))

        data = os.urandom(5 * 1024 * 1024 + 123)
        drops = {"n": 0}

        def flaky(idx: int, attempt: int, chunk: bytes) -> bytes | None:
            if idx == 1 and attempt == 0:
                drops["n"] += 1
                return None  # connectivity lost mid-upload
            if idx == 3 and attempt == 0:
                return bytes([chunk[0] ^ 1]) + chunk[1:]  # bit flip in transit
            return chunk

        cl = UploadClient(
            http, tok(cam.device_id, "device"), cam, fault=flaky, sleep=lambda _: None
        )
        rec = cl.upload(data, sequence_no=1, chunk_size=1024 * 1024, case_id="INC-2026-0042")
        print(f"[1] stored {rec['receipt']['evidence_id']} sha256={rec['receipt']['sha256'][:16]}… "
              f"retries={cl.stats['retries']} resent={cl.stats['resent_chunks']}")  # fmt: skip

        try:
            cl.upload(data, sequence_no=2, chunk_size=1024 * 1024,
                      full_sha256=hashlib.sha256(b"not the file").hexdigest())  # fmt: skip
        except UploadError as e:
            print(f"[2] tampered object refused: {e} -> status {e.status} {e.body.get('reason')}")
        cust = tok("cust-1", "custodian")
        alerts = http.get("/v1/alerts", headers=h(cust)).json()["alerts"]
        print(f"[3] open alerts: {[(a['kind'], a['severity']) for a in alerts]}")
        eid = rec["receipt"]["evidence_id"]
        r = http.get(f"/v1/evidence/{eid}/custody", headers=h(cust)).json()["report"]
        print(f"[4] custody events={len(r['custody_events'])} fixity_ok={r['fixity_ok']} "
              f"audit_chain_ok={r['audit_chain']['ok']}")  # fmt: skip
        v = http.post("/v1/audit/verify", headers=h(tok("aud-1", "auditor"))).json()
        print(f"[5] audit verify: {v['ok']} ({v['entries']} entries)")
        random.seed(0)
        return 0 if v["ok"] and r["fixity_ok"] else 1


def run_seed(http: httpx.Client, token_secret: str, device_id: str | None = None,
             say: Callable[[str], None] = print) -> dict[str, str]:  # fmt: skip
    """Populate a LIVE server with a small, realistic data set so the console has something to show.

    Registers and activates one camera (two different admins), stores one recording, attempts one
    tampered recording (quarantine + alert) and leaves sequence gaps (2 and 3 never arrive intact). Safe to re-run: every run
    uses a fresh device id.
    """
    now = int(time.time() * 1000)

    def h(sub: str, role: str) -> dict[str, str]:
        return {
            "authorization": f"Bearer {issue_token(token_secret, sub, Role(role), 'agency-1', now, 3600)}"
        }

    cam = DeviceIdentity(device_id or f"cam-{secrets.token_hex(2)}", "officer-77", "agency-1")
    r = http.post("/v1/devices", headers=h("seed-admin-a", "admin"), json={
        "device_id": cam.device_id, "public_key": cam.public_hex,
        "officer_id": cam.officer_id, "agency_id": "agency-1"})  # fmt: skip
    r.raise_for_status()
    http.post(
        f"/v1/devices/{cam.device_id}/activate", headers=h("seed-admin-b", "admin")
    ).raise_for_status()
    cl = UploadClient(http, h(cam.device_id, "device")["authorization"].split(" ", 1)[1], cam,
                      sleep=lambda _: None)  # fmt: skip
    data = os.urandom(2 * 1024 * 1024 + 17)
    rec = cl.upload(data, sequence_no=1, chunk_size=1024 * 1024, case_id="INC-2026-0042")
    out = {"device_id": cam.device_id, "evidence_id": rec["receipt"]["evidence_id"]}
    with contextlib.suppress(UploadError):
        cl.upload(data, sequence_no=2, chunk_size=1024 * 1024,
                  full_sha256=hashlib.sha256(b"not the file").hexdigest())  # fmt: skip
    cl.upload(
        os.urandom(300_000), sequence_no=4, chunk_size=1024 * 1024
    )  # sequence 3 never arrives
    alerts = http.get("/v1/alerts", headers=h("seed-auditor", "auditor")).json()["alerts"]
    bad = [a for a in alerts if a["kind"] == "HASH_MISMATCH" and a.get("object_id")]
    if bad:
        out["quarantined_upload_id"] = bad[0]["object_id"]
    for k, v in out.items():
        say(f"{k:22} {v}")
    say(f"Devices page > Sequence gap check for {cam.device_id}: unsent recordings show as gaps.")
    return out


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run_demo())
