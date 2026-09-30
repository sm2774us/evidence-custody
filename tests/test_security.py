from __future__ import annotations

import os
import sqlite3

import pytest

from custody.errors import WormViolation


def test_originals_are_write_once_and_undeletable(env):
    cam, rec = env.stored()
    eid = rec["receipt"]["evidence_id"]
    row = env.svc.db.one("SELECT * FROM evidence WHERE evidence_id=?", (eid,))
    path = env.root / "originals" / row["storage_key"]
    assert oct(path.stat().st_mode & 0o777) == "0o444"
    other = env.root / "x.bin"
    other.write_bytes(b"replacement")
    with pytest.raises(WormViolation):
        env.svc.store.put_original(row["storage_key"], other, "f" * 64, 0)
    with pytest.raises(WormViolation):
        env.svc.delete_original(eid)
    with pytest.raises(WormViolation):
        env.svc.store.extend_retention(row["storage_key"], row["version_id"], 1)  # shortening


def test_db_rejects_update_and_delete_of_evidence_and_audit(env):
    env.stored()
    raw = env.svc.db.raw()
    for sql in ("UPDATE evidence SET sha256='x'", "DELETE FROM evidence",
                "UPDATE audit_log SET actor='mallory'", "DELETE FROM audit_log"):  # fmt: skip
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            raw.execute(sql)


def test_audit_tamper_detected_even_with_trigger_bypass(env):
    env.stored()
    env.svc.audit.checkpoint()
    assert env.svc.audit.verify().ok
    raw = env.svc.db.raw()
    raw.execute("DROP TRIGGER audit_log_no_update")  # attacker with DBA rights
    raw.execute("UPDATE audit_log SET actor='mallory' WHERE seq=2")
    st = env.svc.audit.verify()
    assert not st.ok and st.first_bad_seq == 2
    ready = env.http.get("/readyz")
    assert ready.status_code == 503  # monitoring sees audit-log health failure


def test_truncation_detected_by_checkpoint(env):
    env.stored()
    env.svc.audit.checkpoint()
    raw = env.svc.db.raw()
    raw.execute("DROP TRIGGER audit_log_no_delete")
    last = env.svc.audit.head()[0]
    raw.execute("DELETE FROM audit_log WHERE seq=?", (last,))
    assert not env.svc.audit.verify().ok


def test_admin_cannot_touch_evidence_and_is_flagged(env):
    cam, rec = env.stored()
    eid = rec["receipt"]["evidence_id"]
    r = env.http.get(
        f"/v1/evidence/{eid}/content",
        headers={**env.h("admin-a", "admin"), "x-access-reason": "just looking around"},
    )
    assert r.status_code == 403
    assert env.http.get(f"/v1/evidence/{eid}", headers=env.h("admin-a", "admin")).status_code == 403
    kinds = [a for a in env.svc.db.query("SELECT kind, severity FROM alerts")]
    assert any(
        k["kind"] == "ADMIN_EVIDENCE_ACCESS_ATTEMPT" and k["severity"] == "critical" for k in kinds
    )


def test_auditor_reads_audit_but_not_bytes(env):
    cam, rec = env.stored()
    eid = rec["receipt"]["evidence_id"]
    assert env.http.get("/v1/audit", headers=env.h("aud", "auditor")).status_code == 200
    r = env.http.get(
        f"/v1/evidence/{eid}/content",
        headers={**env.h("aud", "auditor"), "x-access-reason": "audit sampling 2026"},
    )
    assert r.status_code == 403


def test_cross_agency_and_device_isolation(env):
    cam, rec = env.stored()
    eid = rec["receipt"]["evidence_id"]
    r = env.http.get(f"/v1/evidence/{eid}", headers=env.h("cust", "custodian", "agency-2"))
    assert r.status_code == 403
    r = env.http.get(f"/v1/evidence/{eid}", headers=env.h(cam.device_id, "device"))
    assert r.status_code == 403
    sid = rec["receipt"]["session_id"]
    other = env.device("cam-0002")
    r = env.http.get(f"/v1/uploads/{sid}", headers=env.h(other.device_id, "device"))
    assert r.status_code == 403


def test_reason_required_and_access_audited(env):
    cam, rec = env.stored()
    eid = rec["receipt"]["evidence_id"]
    h = env.h("cust", "custodian")
    assert env.http.get(f"/v1/evidence/{eid}/content", headers=h).status_code == 422
    env.http.get(
        f"/v1/evidence/{eid}/content", headers={**h, "x-access-reason": "prosecutor request 55"}
    )
    acts = [e["action"] for e in env.svc.audit.for_objects([eid])]
    assert "evidence.accessed" in acts and "evidence.access.completed" in acts


def test_token_expiry_bad_signature_and_revocation(env):
    from custody.auth import Role

    tok = env.tok("cust", Role.CUSTODIAN, ttl=10)
    h = {"authorization": f"Bearer {tok}"}
    assert env.http.get("/v1/alerts", headers=h).status_code == 200
    env.clock.advance(60_000)
    assert env.http.get("/v1/alerts", headers=h).status_code == 401  # expired credentials
    assert (
        env.http.get("/v1/alerts", headers={"authorization": "Bearer abc.def"}).status_code == 401
    )
    assert env.http.get("/v1/alerts").status_code == 401
    fresh = env.tok("cust", Role.CUSTODIAN)
    jti = __import__("json").loads(
        __import__("base64").urlsafe_b64decode(fresh.split(".")[0] + "==")
    )["jti"]
    env.svc.db.raw().execute("INSERT INTO revoked_tokens VALUES(?,0)", (jti,))
    assert (
        env.http.get("/v1/alerts", headers={"authorization": f"Bearer {fresh}"}).status_code == 401
    )


def test_separation_of_duties_device_and_hold(env):
    cam = env.device()
    env.http.post(
        "/v1/devices",
        headers=env.h("admin-a", "admin"),
        json={
            "device_id": "cam-9",
            "public_key": cam.public_hex,
            "officer_id": "o",
            "agency_id": "agency-1",
        },
    )
    assert (
        env.http.post("/v1/devices/cam-9/activate", headers=env.h("admin-a", "admin")).status_code
        == 403
    )
    _, rec = (
        env.stored(seq=5)
        if False
        else (cam, env.client(cam).upload(os.urandom(300), sequence_no=1, chunk_size=256))
    )
    eid = rec["receipt"]["evidence_id"]
    h = env.http.post(
        f"/v1/evidence/{eid}/holds",
        headers=env.h("cust", "custodian"),
        json={"case_ref": "CASE-1", "reason": "pending litigation"},
    ).json()
    assert (
        env.http.post(
            f"/v1/holds/{h['hold_id']}/approve", headers=env.h("cust", "custodian")
        ).status_code
        == 403
    )
    assert (
        env.http.post(
            f"/v1/holds/{h['hold_id']}/approve", headers=env.h("legal-1", "legal")
        ).status_code
        == 200
    )
    assert env.svc.is_disposable(eid) is False
    assert (
        env.http.post(
            f"/v1/holds/{h['hold_id']}/release", headers=env.h("legal-1", "legal")
        ).status_code
        == 403
    )
    assert (
        env.http.post(
            f"/v1/holds/{h['hold_id']}/release", headers=env.h("legal-2", "legal")
        ).status_code
        == 200
    )
    env.clock.advance(3000 * 86_400_000)
    assert env.svc.is_disposable(eid) is True


def test_repeated_denials_and_bulk_access_raise_alerts(env):
    cam, rec = env.stored()
    eid = rec["receipt"]["evidence_id"]
    for _ in range(3):
        env.http.get(
            f"/v1/evidence/{eid}/content",
            headers={**env.h("aud", "auditor"), "x-access-reason": "x" * 10},
        )
    for _ in range(5):
        env.http.get(
            f"/v1/evidence/{eid}/content",
            headers={**env.h("cust", "custodian"), "x-access-reason": "x" * 10},
        )
    kinds = {r["kind"] for r in env.svc.db.query("SELECT kind FROM alerts")}
    assert {"REPEATED_AUTHZ_DENIALS", "BULK_EVIDENCE_ACCESS"} <= kinds
    assert env.http.post("/v1/audit/scan", headers=env.h("aud", "auditor")).status_code == 200


def test_fixity_detects_out_of_band_modification(env):
    cam, rec = env.stored()
    row = env.svc.db.one("SELECT * FROM evidence")
    assert env.svc.run_fixity()["failed"] == []
    p = env.root / "originals" / row["storage_key"]
    p.chmod(0o644)
    p.write_bytes(b"tampered on disk")
    res = env.svc.run_fixity()
    assert res["failed"] == [row["evidence_id"]]
    assert any(a["kind"] == "FIXITY_FAILURE" and a["severity"] == "critical"
               for a in env.svc.db.query("SELECT kind, severity FROM alerts"))  # fmt: skip
    rep = env.http.get(
        f"/v1/evidence/{row['evidence_id']}/custody", headers=env.h("cust", "custodian")
    ).json()
    assert rep["report"]["fixity_ok"] is False


def test_derivatives_never_replace_original(env):
    cam, rec = env.stored(os.urandom(2048))
    eid = rec["receipt"]["evidence_id"]
    before = env.svc.db.one("SELECT sha256 FROM evidence")["sha256"]
    r = env.http.post(f"/v1/evidence/{eid}/derivatives?kind=redaction", headers={
        **env.h("cust", "custodian"), "content-type": "video/mp4", "x-params": '{"blur":"faces"}'},
        content=b"redacted bytes")  # fmt: skip
    assert r.status_code == 201 and r.json()["parent_sha256"] == before
    assert env.svc.db.one("SELECT sha256 FROM evidence")["sha256"] == before
    assert (
        env.http.post(
            f"/v1/evidence/{eid}/derivatives?kind=bogus",
            headers=env.h("cust", "custodian"),
            content=b"x",
        ).status_code
        == 422
    )
    assert (
        env.http.post(
            f"/v1/evidence/{eid}/derivatives?kind=clip",
            headers=env.h("reader", "reader"),
            content=b"x",
        ).status_code
        == 403
    )


def test_custody_report_signed_and_complete(env):
    from custody.crypto import canonical_json, verify_signature

    cam, rec = env.stored()
    env.svc.audit.checkpoint()
    rep = env.http.get(
        f"/v1/evidence/{rec['receipt']['evidence_id']}/custody", headers=env.h("cust", "custodian")
    ).json()
    assert verify_signature(
        env.svc.signer.public_hex, rep["signature"], canonical_json(rep["report"])
    )
    assert rep["report"]["audit_chain"]["ok"] and rep["report"]["fixity_ok"]
    assert any(e["action"] == "evidence.stored" for e in rep["report"]["custody_events"])
