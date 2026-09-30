from __future__ import annotations

import hashlib
import os

import pytest

from custody.client import UploadError
from custody.crypto import canonical_json, verify_signature

T0 = 1_759_999_000_000  # a retry must resend the identical signed manifest


def test_happy_path_receipt_and_state(env):
    data = os.urandom(10_000)
    cam, rec = env.stored(data)
    r = rec["receipt"]
    assert r["sha256"] == hashlib.sha256(data).hexdigest()
    assert verify_signature(env.svc.signer.public_hex, rec["signature"], canonical_json(r))
    meta = env.http.get(
        f"/v1/evidence/{r['evidence_id']}", headers=env.h("cust", "custodian")
    ).json()
    assert meta["state"] == "available" and meta["size"] == len(data)
    body = env.http.get(
        f"/v1/evidence/{r['evidence_id']}/content",
        headers={**env.h("cust", "custodian"), "x-access-reason": "case review INC-1"},
    )
    assert body.content == data


def test_state_machine_audited(env):
    cam, rec = env.stored()
    sid = rec["receipt"]["session_id"]
    trail = env.http.get(f"/v1/uploads/{sid}/inspect", headers=env.h("aud", "auditor")).json()[
        "audit"
    ]
    assert [e["action"] for e in trail] == [
        "upload.created",
        "upload.uploading",
        "upload.verifying",
        "upload.verified",
        "upload.available",
    ]


def test_resume_after_interruption(env):
    cam = env.device()
    data = os.urandom(5000)
    calls = {"n": 0}

    def drop_all_after_two(idx, attempt, chunk):
        calls["n"] += 1
        return chunk if idx < 2 else None

    c1 = env.client(cam, fault=drop_all_after_two, max_retries=1)
    with pytest.raises(UploadError):
        c1.upload(data, sequence_no=1, chunk_size=1024, idempotency_key="k" * 20, captured_at_ms=T0)
    # A fresh client (e.g. after reboot) resumes with the same key and only sends what's missing.
    sent = []
    c2 = env.client(cam, fault=lambda i, a, ch: (sent.append(i), ch)[1])
    rec = c2.upload(
        data, sequence_no=1, chunk_size=1024, idempotency_key="k" * 20, captured_at_ms=T0
    )
    assert sent == [2, 3, 4] and rec["receipt"]["size"] == 5000


def test_duplicate_requests_are_idempotent(env):
    cam = env.device()
    cl = env.client(cam)
    data = os.urandom(2500)
    a = cl.upload(data, sequence_no=1, chunk_size=1024, idempotency_key="i" * 20, captured_at_ms=T0)
    b = cl.upload(data, sequence_no=1, chunk_size=1024, idempotency_key="i" * 20, captured_at_ms=T0)
    assert a["receipt"]["evidence_id"] == b["receipt"]["evidence_id"]
    n = env.svc.db.one("SELECT COUNT(*) c FROM evidence")["c"]
    assert n == 1
    # same capture under a new key is deduplicated, not stored twice
    with pytest.raises(UploadError) as e:
        cl.upload(data, sequence_no=1, chunk_size=1024, idempotency_key="j" * 20, captured_at_ms=T0)
    assert e.value.status == 409


def test_corrupt_chunk_rejected_then_retried(env):
    cam = env.device()
    cl = env.client(
        cam, fault=lambda i, a, ch: bytes([ch[0] ^ 1]) + ch[1:] if (i == 1 and a == 0) else ch
    )
    cl.upload(os.urandom(4096), sequence_no=1, chunk_size=1024)
    assert cl.stats["resent_chunks"] == 1
    assert env.svc.metrics.value("custody_chunks_total", result="rejected") == 1


def test_object_hash_mismatch_quarantines_and_alerts(env):
    cam = env.device()
    cl = env.client(cam)
    with pytest.raises(UploadError) as e:
        cl.upload(os.urandom(3000), sequence_no=1, chunk_size=1024, full_sha256="0" * 63 + "1")
    assert e.value.status == 422 and e.value.body["error"] == "quarantined"
    row = env.svc.db.one("SELECT * FROM sessions")
    assert row["state"] == "quarantined"
    assert env.svc.db.one("SELECT COUNT(*) c FROM evidence")["c"] == 0  # never exposed as evidence
    assert (env.root / "quarantine" / row["session_id"] / "0").exists()  # received bytes preserved
    alerts = env.http.get("/v1/alerts", headers=env.h("cust", "custodian")).json()["alerts"]
    assert alerts[0]["kind"] == "HASH_MISMATCH"
    actions = [x["action"] for x in env.svc.audit.for_objects([row["session_id"]])]
    assert (
        "upload.quarantined" in actions and "alert.raised" not in actions
    )  # alert is its own object
    # re-completing does not resurrect it
    r = env.http.post(
        f"/v1/uploads/{row['session_id']}/complete", headers=env.h(cam.device_id, "device")
    )
    assert r.status_code == 422


def test_quarantined_sequence_needs_custodian_review(env):
    cam = env.device()
    cl = env.client(cam)
    data = os.urandom(2000)
    with pytest.raises(UploadError):
        cl.upload(data, sequence_no=7, chunk_size=1024, full_sha256="a" * 64)
    with pytest.raises(UploadError) as e:
        cl.upload(data, sequence_no=7, chunk_size=1024)
    assert e.value.status == 409
    sid = env.svc.db.one("SELECT session_id FROM sessions")["session_id"]
    r = env.http.post(
        f"/v1/quarantine/{sid}/disposition",
        headers=env.h("cust", "custodian"),
        json={"decision": "retry_authorized", "note": "device reflashed, retry ok"},
    )
    assert r.status_code == 200
    assert cl.upload(data, sequence_no=7, chunk_size=1024)["receipt"]["sequence_no"] == 7


def test_invalid_signature_rejected(env):
    cam = env.device()
    other = env.device("cam-0002")
    cl = env.client(cam)
    cl.id = type(cam)(cam.device_id, cam.officer_id, cam.agency_id)  # wrong private key
    with pytest.raises(UploadError) as e:
        cl.upload(os.urandom(100), sequence_no=1, chunk_size=64)
    assert e.value.status == 422
    kinds = [a["kind"] for a in env.svc.list_alerts(_aud(env), "open", _ctx())]
    assert "SIGNATURE_INVALID" in kinds and other


def test_sequence_conflict_is_critical(env):
    cam = env.device()
    cl = env.client(cam)
    cl.upload(os.urandom(500), sequence_no=3, chunk_size=256)
    with pytest.raises(UploadError):
        cl.upload(os.urandom(500), sequence_no=3, chunk_size=256)
    a = [
        x
        for x in env.svc.list_alerts(_aud(env), "open", _ctx())
        if x["kind"] == "SEQUENCE_CONFLICT"
    ]
    assert a and a[0]["severity"] == "critical"


def test_future_dated_capture_flagged_not_rejected(env):
    cam = env.device()
    env.client(cam).upload(os.urandom(300), sequence_no=1, chunk_size=256,
                           captured_at_ms=env.clock() + 3 * 3600 * 1000)  # fmt: skip
    kinds = [a["kind"] for a in env.svc.list_alerts(_aud(env), "open", _ctx())]
    assert "CLOCK_FUTURE_CAPTURE" in kinds


def test_expired_sessions_and_gaps(env):
    cam = env.device()
    cl = env.client(cam)
    cl.upload(os.urandom(300), sequence_no=0, chunk_size=256)
    cl.upload(os.urandom(300), sequence_no=2, chunk_size=256)
    gaps = env.http.get(
        f"/v1/devices/{cam.device_id}/sequence-gaps", headers=env.h("cust", "custodian")
    ).json()
    assert gaps["missing"] == [1]
    from custody.device import ChunkSource, build_manifest

    m, sig = build_manifest(cam, ChunkSource(b"z" * 300, 256), sequence_no=5)
    env.http.post(
        "/v1/uploads",
        headers=env.h(cam.device_id, "device"),
        json={"manifest": m, "signature": sig},
    )
    env.clock.advance(80 * 3600 * 1000)
    assert env.svc.expire_stale() == 1


def _aud(env):
    from custody.auth import Principal, Role

    return Principal("aud", Role.CUSTODIAN, "agency-1")


def _ctx():
    from custody.audit import Ctx

    return Ctx()
