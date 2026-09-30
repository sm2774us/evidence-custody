"""EvidenceService: the stateful, idempotent ingest workflow.

Invariants
  1. Nothing is acknowledged until the object is durably stored AND re-read and re-hashed.
  2. Every state transition commits atomically with its audit row (single transaction).
  3. Originals are write-once; derivatives reference an original and can never replace it.
  4. Deterministic checks decide accept/quarantine. AI (triage) is advisory only."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .audit import SYSTEM, Actor, AuditLog, Clock, Ctx
from .auth import Principal, Role
from .config import Settings
from .crypto import Signer, canonical_json, sha256_hex, verify_signature
from .db import Database
from .errors import (
    Conflict,
    Forbidden,
    IntegrityFailure,
    NotFound,
    Quarantined,
    ValidationFailed,
    WormViolation,
)  # fmt: skip
from .metrics import Metrics
from .models import TRANSITIONS, DerivativeKind, Manifest, SessionState
from .storage import ObjectStore, Staging
from .triage import Advisory, Triage

DAY_MS = 86_400_000


def _actor(p: Principal) -> Actor:
    return Actor(p.sub, p.role.value)


class EvidenceService:
    def __init__(self, settings: Settings, db: Database, audit: AuditLog, store: ObjectStore,
                 staging: Staging, signer: Signer, clock: Clock, metrics: Metrics,
                 triage: Triage) -> None:  # fmt: skip
        self.s, self.db, self.audit, self.store, self.staging = settings, db, audit, store, staging
        self.signer, self.clock, self.metrics, self.triage = signer, clock, metrics, triage
        metrics.gauge("custody_oldest_open_upload_age_seconds", self._oldest_open_age)
        metrics.gauge("custody_open_alerts", lambda: float(self._count("alerts", "status='open'")))
        metrics.gauge("custody_quarantined_sessions",
                      lambda: float(self._count("sessions", "state='quarantined'")))  # fmt: skip

    # ---- helpers -----------------------------------------------------------------------
    def _count(self, table: str, where: str, args: tuple[Any, ...] = ()) -> int:
        r = self.db.one(f"SELECT COUNT(*) c FROM {table} WHERE {where}", args)  # noqa: S608
        return int(r["c"]) if r else 0

    def _oldest_open_age(self) -> float:
        r = self.db.one(
            "SELECT MIN(created_at) m FROM sessions WHERE state IN ('created','uploading')"
        )
        return (self.clock() - r["m"]) / 1000 if r and r["m"] else 0.0

    def _deny(self, p: Principal, perm: str, ctx: Ctx, obj: str = "-") -> None:
        with self.db.tx() as c:
            self.audit.append(c, _actor(p), "authz.denied", "permission", obj,
                              {"permission": perm}, ctx=ctx)  # fmt: skip
        self.metrics.inc("custody_authz_denied_total", role=p.role.value)
        if p.role is Role.ADMIN and perm.startswith("evidence:"):
            self._alert("ADMIN_EVIDENCE_ACCESS_ATTEMPT", "access_anomaly", p.sub,
                        {"event": "access_anomaly", "role": "admin", "denied_in_window": 1})  # fmt: skip
        else:
            self._scan_denials(p, ctx)
        raise Forbidden(f"missing permission {perm}")

    def _require(self, p: Principal, perm: str, ctx: Ctx, obj: str = "-") -> None:
        if not p.can(perm):
            self._deny(p, perm, ctx, obj)

    def _alert(self, kind: str, event: str, object_id: str, ctx: dict[str, Any],
               dedupe_ms: int = 0) -> dict[str, Any]:  # fmt: skip
        advisory = self.triage.assess({**ctx, "event": ctx.get("event", event)})
        now = self.clock()
        if dedupe_ms:
            dup = self.db.one("SELECT alert_id FROM alerts WHERE kind=? AND object_id=? AND "
                              "status='open' AND ts_ms>?", (kind, object_id, now - dedupe_ms))  # fmt: skip
            if dup:
                return {"alert_id": dup["alert_id"], "deduplicated": True}
        aid = f"al_{uuid.uuid4().hex[:16]}"
        detail = {"advisory": advisory.model_dump(), "object_id": object_id}
        with self.db.tx() as c:
            c.execute("INSERT INTO alerts(alert_id,ts_ms,kind,severity,object_id,detail_json) "
                      "VALUES(?,?,?,?,?,?)",
                      (aid, now, kind, advisory.severity, object_id, json.dumps(detail)))  # fmt: skip
            self.audit.append(c, SYSTEM, "alert.raised", "alert", aid,
                              {"kind": kind, "severity": advisory.severity,
                               "advisory_source": advisory.source, "model": advisory.model,
                               "prompt_sha256": advisory.prompt_sha256})  # fmt: skip
        self.metrics.inc("custody_alerts_total", kind=kind, severity=advisory.severity)
        return {"alert_id": aid, "advisory": advisory.model_dump()}

    def _scan_denials(self, p: Principal, ctx: Ctx) -> None:
        w = self.clock() - self.s.download_window_ms
        r = self.db.one("SELECT COUNT(*) c FROM audit_log WHERE actor=? AND action='authz.denied' "
                        "AND ts_ms>?", (p.sub, w))  # fmt: skip
        n = int(r["c"]) if r else 0
        if n >= self.s.denied_alert_threshold:
            self._alert("REPEATED_AUTHZ_DENIALS", "access_anomaly", p.sub,
                        {"role": p.role.value, "denied_in_window": n},
                        dedupe_ms=self.s.download_window_ms)  # fmt: skip

    def _transition(self, c: sqlite3.Connection, sid: str, cur: SessionState, new: SessionState,
                    actor: Actor, detail: dict[str, Any] | None = None, ctx: Ctx = Ctx(),  # noqa: B008
                    evidence_id: str | None = None, reason: str | None = None) -> None:  # fmt: skip
        if new not in TRANSITIONS[cur]:
            raise Conflict(f"illegal transition {cur.value} -> {new.value}")
        n = c.execute("UPDATE sessions SET state=?, updated_at=?, evidence_id=COALESCE(?,evidence_id),"
                      " failure_reason=COALESCE(?,failure_reason) WHERE session_id=? AND state=?",
                      (new.value, self.clock(), evidence_id, reason, sid, cur.value)).rowcount  # fmt: skip
        if n != 1:
            raise Conflict("concurrent state change; retry")
        self.audit.append(c, actor, f"upload.{new.value}", "upload", sid,
                          {"from": cur.value, **(detail or {})}, ctx=ctx)  # fmt: skip
        self.metrics.inc("custody_upload_transitions_total", to=new.value)

    def _session(self, sid: str) -> sqlite3.Row:
        r = self.db.one("SELECT * FROM sessions WHERE session_id=?", (sid,))
        if not r:
            raise NotFound("upload session not found")
        return r

    def _own_session(self, p: Principal, sid: str, perm: str, ctx: Ctx) -> sqlite3.Row:
        self._require(p, perm, ctx, sid)
        r = self._session(sid)
        if r["device_id"] != p.sub or r["agency_id"] != p.agency:
            self._deny(p, "upload:foreign", ctx, sid)
        return r

    def _evidence(self, p: Principal, eid: str, perm: str, ctx: Ctx) -> sqlite3.Row:
        self._require(p, perm, ctx, eid)
        r = self.db.one("SELECT * FROM evidence WHERE evidence_id=?", (eid,))
        if not r or r["agency_id"] != p.agency:  # cross-agency looks identical to absent
            if r:
                self._deny(p, "evidence:cross-agency", ctx, eid)
            raise NotFound("evidence not found")
        return r

    # ---- devices (separation of duties) ------------------------------------------------
    def register_device(self, p: Principal, device_id: str, public_key: str, officer_id: str,
                        agency_id: str, ctx: Ctx) -> dict[str, Any]:  # fmt: skip
        self._require(p, "device:register", ctx, device_id)
        if agency_id != p.agency:
            self._deny(p, "device:cross-agency", ctx, device_id)
        with self.db.tx() as c:
            if c.execute("SELECT 1 FROM devices WHERE device_id=?", (device_id,)).fetchone():
                raise Conflict("device already registered")
            c.execute("INSERT INTO devices VALUES(?,?,?,?,?,?,NULL,?)",
                      (device_id, public_key, officer_id, agency_id, "pending", p.sub, self.clock()))  # fmt: skip
            self.audit.append(c, _actor(p), "device.registered", "device", device_id,
                              {"public_key": public_key, "officer_id": officer_id}, ctx=ctx)  # fmt: skip
        return {"device_id": device_id, "status": "pending"}

    def activate_device(self, p: Principal, device_id: str, ctx: Ctx) -> dict[str, Any]:
        self._require(p, "device:activate", ctx, device_id)
        with self.db.tx() as c:
            d = c.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
            if not d or d["agency_id"] != p.agency:
                raise NotFound("device not found")
            if d["registered_by"] == p.sub:
                raise Forbidden("separation of duties: a second administrator must activate")
            if d["status"] != "pending":
                raise Conflict(f"device is {d['status']}")
            c.execute("UPDATE devices SET status='active', activated_by=? WHERE device_id=?",
                      (p.sub, device_id))  # fmt: skip
            self.audit.append(c, _actor(p), "device.activated", "device", device_id, ctx=ctx)
        return {"device_id": device_id, "status": "active"}

    def revoke_device(self, p: Principal, device_id: str, reason: str, ctx: Ctx) -> dict[str, Any]:
        self._require(p, "device:revoke", ctx, device_id)
        with self.db.tx() as c:
            n = c.execute("UPDATE devices SET status='revoked' WHERE device_id=? AND agency_id=?",
                          (device_id, p.agency)).rowcount  # fmt: skip
            if not n:
                raise NotFound("device not found")
            self.audit.append(c, _actor(p), "device.revoked", "device", device_id,
                              {"reason": reason[:200]}, ctx=ctx)  # fmt: skip
        return {"device_id": device_id, "status": "revoked"}

    def sequence_gaps(self, p: Principal, device_id: str, ctx: Ctx) -> list[int]:
        self._require(p, "evidence:read", ctx, device_id)
        rows = self.db.query("SELECT sequence_no s FROM evidence WHERE device_id=? AND agency_id=? "
                             "ORDER BY s", (device_id, p.agency))  # fmt: skip
        have = {r["s"] for r in rows}
        return [i for i in range(max(have) + 1) if i not in have] if have else []

    # ---- upload workflow ---------------------------------------------------------------
    def create_upload(self, p: Principal, manifest_raw: dict[str, Any], signature: str,
                      ctx: Ctx) -> dict[str, Any]:  # fmt: skip
        self._require(p, "upload:create", ctx)
        try:
            m = Manifest.model_validate(manifest_raw)
        except ValidationError as e:
            raise ValidationFailed("invalid manifest", errors=json.loads(e.json())) from e
        if m.device_id != p.sub or m.agency_id != p.agency:
            self._deny(p, "upload:impersonate", ctx, m.device_id)
        if m.chunk_size > self.s.max_chunk_bytes or m.size > self.s.max_object_bytes:
            raise ValidationFailed("chunk_size or size exceeds limits")
        dev = self.db.one("SELECT * FROM devices WHERE device_id=?", (m.device_id,))
        if not dev or dev["status"] != "active":
            raise Forbidden("device is not active")
        mbytes = canonical_json(m.wire())
        if not verify_signature(dev["public_key"], signature, mbytes):
            self._integrity_event("SIGNATURE_INVALID", "signature_invalid", m.device_id, p, ctx,
                                  {"device_id": m.device_id})  # fmt: skip
            raise IntegrityFailure("manifest signature invalid")
        mhash = sha256_hex(mbytes)
        now = self.clock()
        skew = m.captured_at_ms - now if m.captured_at_ms > now + self.s.future_skew_ms else None

        with self.db.tx() as c:
            ex = c.execute("SELECT * FROM sessions WHERE device_id=? AND idempotency_key=?",
                           (m.device_id, m.idempotency_key)).fetchone()  # fmt: skip
            if ex:
                if ex["manifest_hash"] != mhash:
                    conflict = "idempotency key reused with a different manifest"
                else:
                    self.metrics.inc("custody_idempotent_replays_total", op="create")
                    return self._session_view(ex)
            else:
                conflict = ""
                dupe = c.execute("SELECT evidence_id, sha256 FROM evidence WHERE device_id=? AND "
                                 "sequence_no=?", (m.device_id, m.sequence_no)).fetchone()  # fmt: skip
                if dupe and dupe["sha256"] == m.sha256:
                    raise Conflict(
                        "this capture is already stored", evidence_id=dupe["evidence_id"]
                    )
                if dupe:
                    conflict = "sequence number already bound to different content"
                q = c.execute("SELECT session_id FROM sessions WHERE device_id=? AND sequence_no=? "
                              "AND state='quarantined' AND retry_authorized=0",
                              (m.device_id, m.sequence_no)).fetchone()  # fmt: skip
                if q and not conflict:
                    raise Conflict("prior upload of this sequence is quarantined; custodian review "
                                   "required", session_id=q["session_id"])  # fmt: skip
        if conflict:
            self._integrity_event("SEQUENCE_CONFLICT" if "sequence" in conflict else
                                  "IDEMPOTENCY_CONFLICT", "sequence_conflict", m.device_id, p, ctx,
                                  {"device_id": m.device_id})  # fmt: skip
            raise Conflict(conflict)

        sid = f"up_{uuid.uuid4().hex[:20]}"
        try:
            with self.db.tx() as c:
                c.execute("INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?,NULL,NULL,0,?,?)",
                          (sid, m.device_id, m.agency_id, m.idempotency_key, mhash,
                           json.dumps(m.wire()), m.sequence_no, "created", now, now))  # fmt: skip
                self.audit.append(c, _actor(p), "upload.created", "upload", sid,
                                  {"manifest_sha256": mhash, "object_sha256": m.sha256,
                                   "size": m.size, "chunks": len(m.chunk_sha256),
                                   "sequence_no": m.sequence_no, "case_id": m.case_id,
                                   "officer_id": m.officer_id, "captured_at_ms": m.captured_at_ms,
                                   "future_skew_ms": skew}, ctx=ctx)  # fmt: skip
        except sqlite3.IntegrityError as e:  # racing duplicate create: replay the winner
            r = self.db.one("SELECT * FROM sessions WHERE device_id=? AND idempotency_key=?",
                            (m.device_id, m.idempotency_key))  # fmt: skip
            if r and r["manifest_hash"] == mhash:
                return self._session_view(r)
            raise Conflict("sequence number is already being uploaded") from e
        if skew is not None:
            self._alert("CLOCK_FUTURE_CAPTURE", "clock_future", sid,
                        {"event": "clock_future", "future_skew_ms": skew})  # fmt: skip
        self.metrics.inc("custody_uploads_created_total")
        return self._session_view(self._session(sid))

    def _integrity_event(self, kind: str, event: str, subject: str, p: Principal, ctx: Ctx,
                         extra: dict[str, Any]) -> None:  # fmt: skip
        prior = self._count("alerts", "object_id=?", (subject,))
        with self.db.tx() as c:
            self.audit.append(c, _actor(p), f"integrity.{kind.lower()}", "device", subject,
                              extra, ctx=ctx)  # fmt: skip
        self.metrics.inc("custody_integrity_events_total", kind=kind)
        self._alert(
            kind, event, subject, {**extra, "event": event, "device_prior_incidents": prior}
        )

    def _session_view(self, r: sqlite3.Row) -> dict[str, Any]:
        have = [x["idx"] for x in self.db.query(
            "SELECT idx FROM chunks WHERE session_id=? ORDER BY idx", (r["session_id"],))]  # fmt: skip
        total = len(json.loads(r["manifest_json"])["chunk_sha256"])
        return {"session_id": r["session_id"], "state": r["state"], "evidence_id": r["evidence_id"],
                "received_chunks": have, "missing_chunks": [i for i in range(total) if i not in set(have)],
                "chunk_count": total, "failure_reason": r["failure_reason"]}  # fmt: skip

    def upload_status(self, p: Principal, sid: str, ctx: Ctx) -> dict[str, Any]:
        return self._session_view(self._own_session(p, sid, "upload:read", ctx))

    def upload_inspect(self, p: Principal, sid: str, ctx: Ctx) -> dict[str, Any]:
        self._require(p, "upload:inspect", ctx, sid)
        r = self._session(sid)
        if r["agency_id"] != p.agency:
            raise NotFound("upload session not found")
        trail = [
            e
            for e in self.audit.for_objects([sid])
            if e["action"].startswith(("upload.", "chunk."))
        ]
        return {**self._session_view(r), "audit": trail}

    def put_chunk(self, p: Principal, sid: str, idx: int, data: bytes, ctx: Ctx) -> dict[str, Any]:
        r = self._own_session(p, sid, "upload:write", ctx)
        state = SessionState(r["state"])
        if state not in (SessionState.CREATED, SessionState.UPLOADING):
            raise Conflict(f"upload is {state.value}; chunks no longer accepted")
        if self.clock() - r["created_at"] > self.s.session_ttl_hours * 3_600_000:
            self._expire(sid)
            raise Conflict("upload session expired")
        m = Manifest.model_validate(json.loads(r["manifest_json"]))
        if not 0 <= idx < len(m.chunk_sha256):
            raise ValidationFailed("chunk index out of range")
        if len(data) != m.expected_chunk_len(idx):
            self._reject_chunk(p, sid, idx, "length", ctx)
        got = sha256_hex(data)
        if got != m.chunk_sha256[idx]:
            self._reject_chunk(p, sid, idx, "hash", ctx, got)
        self.staging.put_chunk(sid, idx, data)
        with self.db.tx() as c:
            fresh = c.execute("INSERT OR IGNORE INTO chunks VALUES(?,?,?,?)",
                              (sid, idx, got, len(data))).rowcount == 1  # fmt: skip
            if state is SessionState.CREATED:
                self._transition(c, sid, SessionState.CREATED, SessionState.UPLOADING,
                                 _actor(p), {"first_chunk": idx}, ctx)  # fmt: skip
        self.metrics.inc("custody_chunks_total", result="stored" if fresh else "duplicate")
        return {"index": idx, "status": "stored" if fresh else "duplicate"}

    def _reject_chunk(self, p: Principal, sid: str, idx: int, why: str, ctx: Ctx,
                      got: str = "") -> None:  # fmt: skip
        with self.db.tx() as c:
            self.audit.append(c, _actor(p), "chunk.rejected", "upload", sid,
                              {"index": idx, "reason": why, "received_sha256": got}, ctx=ctx)  # fmt: skip
        self.metrics.inc("custody_chunks_total", result="rejected")
        raise IntegrityFailure("chunk failed verification; resend", index=idx, retryable=True)

    def _expire(self, sid: str) -> None:
        r = self._session(sid)
        cur = SessionState(r["state"])
        if TRANSITIONS[cur] and SessionState.EXPIRED in TRANSITIONS[cur]:
            with self.db.tx() as c:
                self._transition(
                    c, sid, cur, SessionState.EXPIRED, SYSTEM, {"ttl_h": self.s.session_ttl_hours}
                )
            self.staging.cleanup(sid)

    def expire_stale(self) -> int:
        cutoff = self.clock() - self.s.session_ttl_hours * 3_600_000
        rows = self.db.query("SELECT session_id FROM sessions WHERE state IN ('created','uploading') "
                             "AND created_at<?", (cutoff,))  # fmt: skip
        for r in rows:
            self._expire(r["session_id"])
        return len(rows)

    def complete(self, p: Principal, sid: str, ctx: Ctx) -> dict[str, Any]:
        r = self._own_session(p, sid, "upload:write", ctx)
        state = SessionState(r["state"])
        if state is SessionState.AVAILABLE:
            self.metrics.inc("custody_idempotent_replays_total", op="complete")
            return self._receipt_for(r["evidence_id"])
        if state is SessionState.QUARANTINED:
            raise Quarantined("upload is quarantined and not verified", session_id=sid,
                              reason=r["failure_reason"])  # fmt: skip
        if state is not SessionState.UPLOADING:
            raise Conflict(f"cannot complete an upload in state {state.value}")
        m = Manifest.model_validate(json.loads(r["manifest_json"]))
        view = self._session_view(r)
        if view["missing_chunks"]:
            raise Conflict("chunks missing", missing_chunks=view["missing_chunks"])
        with self.db.tx() as c:
            self._transition(
                c, sid, SessionState.UPLOADING, SessionState.VERIFYING, _actor(p), ctx=ctx
            )

        eid = "ev_" + sid[3:]
        with tempfile.TemporaryDirectory(dir=self.staging.root) as td:
            tmp = Path(td) / "object"
            self.staging.assemble(sid, len(m.chunk_sha256), tmp)
            actual, size = _hash_path(tmp)
            if actual != m.sha256 or size != m.size:
                self._quarantine(p, r, m, "object_hash_mismatch", actual, size, ctx)
            key = f"{m.agency_id}/{m.sha256[:2]}/{eid}"
            until = self.clock() + self.s.retention_days[m.retention_class] * DAY_MS
            version = self.store.put_original(key, tmp, m.sha256, until)
        with self.store.open_original(key, version) as f:  # read-after-write verification
            stored = _hash_stream(f)
        if stored != m.sha256:
            self._quarantine(p, r, m, "stored_object_mismatch", stored, size, ctx)

        now = self.clock()
        with self.db.tx() as c:
            self._transition(c, sid, SessionState.VERIFYING, SessionState.VERIFIED, SYSTEM,
                             {"sha256": actual, "size": size}, ctx, reason=None)  # fmt: skip
            seq = self.audit.append(c, SYSTEM, "evidence.stored", "evidence", eid,
                                    {"storage_key": key, "retention_until_ms": until,
                                     "sha256": actual, "size": size},
                                    object_version=version, ctx=ctx)  # fmt: skip
            receipt = {"evidence_id": eid, "session_id": sid, "sha256": actual, "size": size,
                       "device_id": m.device_id, "sequence_no": m.sequence_no,
                       "retention_until_ms": until, "version_id": version, "stored_at_ms": now,
                       "audit_seq": seq, "key_id": self.signer.key_id}  # fmt: skip
            sig = self.signer.sign_obj(receipt)
            c.execute("INSERT INTO evidence VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (eid, sid, m.agency_id, m.device_id, m.officer_id, m.case_id, m.sequence_no,
                       actual, size, m.media_type, key, version, until, m.captured_at_ms, now,
                       None, json.dumps(receipt, sort_keys=True), sig))  # fmt: skip
            self._transition(c, sid, SessionState.VERIFIED, SessionState.AVAILABLE, SYSTEM,
                             {"evidence_id": eid}, ctx, evidence_id=eid)  # fmt: skip
        self.staging.cleanup(sid)
        self.metrics.inc("custody_evidence_stored_total")
        return {"receipt": receipt, "signature": sig}

    def _receipt_for(self, eid: str) -> dict[str, Any]:
        e = self.db.one(
            "SELECT receipt_json, receipt_sig FROM evidence WHERE evidence_id=?", (eid,)
        )
        if not e:
            raise NotFound("evidence not found")
        return {"receipt": json.loads(e["receipt_json"]), "signature": e["receipt_sig"]}

    def _quarantine(self, p: Principal, r: sqlite3.Row, m: Manifest, reason: str, actual: str,
                    size: int, ctx: Ctx) -> None:  # fmt: skip
        sid = r["session_id"]
        path = self.staging.quarantine(sid)
        rej = self._count("audit_log", "object_id=? AND action='chunk.rejected'", (sid,))
        with self.db.tx() as c:
            self._transition(c, sid, SessionState.VERIFYING, SessionState.QUARANTINED, SYSTEM,
                             {"reason": reason, "expected_sha256": m.sha256, "actual_sha256": actual,
                              "expected_size": m.size, "actual_size": size,
                              "preserved_at": path.name}, ctx, reason=reason)  # fmt: skip
        self.metrics.inc("custody_hash_mismatch_total")
        prior = self._count("sessions", "device_id=? AND state='quarantined'", (m.device_id,)) - 1
        self._alert("HASH_MISMATCH", "hash_mismatch", sid,
                    {"event": "hash_mismatch", "rejected_chunks": rej, "all_chunks_verified": True,
                     "device_prior_incidents": max(prior, 0), "device_id": m.device_id,
                     "size": m.size, "chunk_count": len(m.chunk_sha256)})  # fmt: skip
        raise Quarantined(
            "object hash mismatch; upload quarantined, not acknowledged",
            session_id=sid,
            reason=reason,
        )

    # ---- quarantine review -------------------------------------------------------------
    def disposition(
        self, p: Principal, sid: str, decision: str, note: str, ctx: Ctx
    ) -> dict[str, Any]:
        self._require(p, "quarantine:review", ctx, sid)
        r = self._session(sid)
        if r["agency_id"] != p.agency or r["state"] != SessionState.QUARANTINED.value:
            raise NotFound("no such quarantined upload")
        with self.db.tx() as c:
            if decision == "retry_authorized":
                c.execute("UPDATE sessions SET retry_authorized=1 WHERE session_id=?", (sid,))
            self.audit.append(c, _actor(p), f"quarantine.{decision}", "upload", sid,
                              {"note": note}, ctx=ctx)  # fmt: skip
        return {"session_id": sid, "decision": decision}

    def triage_session(self, p: Principal, sid: str, ctx: Ctx) -> Advisory:
        self._require(p, "triage:run", ctx, sid)
        r = self._session(sid)
        if r["agency_id"] != p.agency:
            raise NotFound("upload session not found")
        rej = self._count("audit_log", "object_id=? AND action='chunk.rejected'", (sid,))
        ev = "hash_mismatch" if r["state"] == "quarantined" else "benign"
        adv = self.triage.assess({"event": ev, "rejected_chunks": rej, "all_chunks_verified": True,
                                  "session_id": sid, "device_id": r["device_id"]})  # fmt: skip
        with self.db.tx() as c:
            self.audit.append(c, _actor(p), "triage.advisory", "upload", sid,
                              {"category": adv.category, "severity": adv.severity,
                               "source": adv.source, "model": adv.model,
                               "prompt_sha256": adv.prompt_sha256}, ctx=ctx)  # fmt: skip
        return adv

    # ---- reads -------------------------------------------------------------------------
    def get_evidence(self, p: Principal, eid: str, ctx: Ctx) -> dict[str, Any]:
        e = self._evidence(p, eid, "evidence:read", ctx)
        with self.db.tx() as c:
            self.audit.append(c, _actor(p), "evidence.viewed", "evidence", eid,
                              object_version=e["version_id"], ctx=ctx)  # fmt: skip
        keep = ("evidence_id", "agency_id", "device_id", "officer_id", "case_id", "sequence_no",
                "sha256", "size", "media_type", "version_id", "retention_until_ms",
                "captured_at_ms", "received_at_ms")  # fmt: skip
        holds = self.db.query(
            "SELECT hold_id,case_ref,status FROM legal_holds WHERE evidence_id=?", (eid,)
        )
        return {
            **{k: e[k] for k in keep},
            "state": "available",
            "legal_holds": [dict(h) for h in holds],
        }

    def open_content(
        self, p: Principal, eid: str, reason: str, ctx: Ctx
    ) -> tuple[Iterator[bytes], dict[str, Any]]:
        e = self._evidence(p, eid, "evidence:download", ctx)
        if len(reason.strip()) < 8:
            raise ValidationFailed("X-Access-Reason (>= 8 chars) is required to access evidence")
        with self.db.tx() as c:
            self.audit.append(c, _actor(p), "evidence.accessed", "evidence", eid,
                              {"reason": reason.strip()[:300]}, object_version=e["version_id"], ctx=ctx)  # fmt: skip
        self.metrics.inc("custody_evidence_access_total")
        self._scan_downloads(p)
        f = self.store.open_original(e["storage_key"], e["version_id"])

        def gen() -> Iterator[bytes]:
            h = hashlib.sha256()
            with f:
                for blk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(blk)
                    yield blk
            ok = h.hexdigest() == e["sha256"]
            with self.db.tx() as c:
                self.audit.append(c, _actor(p), "evidence.access.completed", "evidence", eid,
                                  {"verified_on_read": ok}, object_version=e["version_id"], ctx=ctx)  # fmt: skip
            if not ok:
                self._alert("FIXITY_FAILURE", "fixity_failure", eid, {"event": "fixity_failure"})

        return gen(), {"sha256": e["sha256"], "size": e["size"], "media_type": e["media_type"]}

    def _scan_downloads(self, p: Principal) -> None:
        w = self.clock() - self.s.download_window_ms
        r = self.db.one("SELECT COUNT(*) c, COUNT(DISTINCT object_id) d FROM audit_log WHERE "
                        "actor=? AND action='evidence.accessed' AND ts_ms>?", (p.sub, w))  # fmt: skip
        if r and r["c"] >= self.s.download_alert_threshold:
            self._alert("BULK_EVIDENCE_ACCESS", "access_anomaly", p.sub,
                        {"role": p.role.value, "downloads_in_window": int(r["c"]),
                         "distinct_evidence": int(r["d"])}, dedupe_ms=self.s.download_window_ms)  # fmt: skip

    def scan_audit(self, p: Principal, ctx: Ctx) -> list[dict[str, Any]]:
        """Retrospective anomaly scan over the audit trail (also run by the scheduled job)."""
        self._require(p, "audit:scan", ctx)
        w = self.clock() - self.s.download_window_ms
        out = []
        for r in self.db.query(
            "SELECT actor, actor_role, SUM(action='evidence.accessed') dl, "
            "SUM(action='authz.denied') dn, COUNT(DISTINCT CASE WHEN action='evidence.accessed' "
            "THEN object_id END) de FROM audit_log WHERE ts_ms>? GROUP BY actor", (w,)):  # fmt: skip
            if (r["dl"] or 0) >= self.s.download_alert_threshold or (
                r["dn"] or 0
            ) >= self.s.denied_alert_threshold:
                out.append(self._alert("ACCESS_PATTERN_ANOMALY", "access_anomaly", r["actor"],
                                       {"role": r["actor_role"], "downloads_in_window": r["dl"] or 0,
                                        "denied_in_window": r["dn"] or 0, "distinct_evidence": r["de"] or 0},
                                       dedupe_ms=self.s.download_window_ms))  # fmt: skip
        return out

    # ---- derivatives -------------------------------------------------------------------
    def create_derivative(self, p: Principal, eid: str, kind: str, data: bytes, media_type: str,
                          params: dict[str, Any], ctx: Ctx) -> dict[str, Any]:  # fmt: skip
        e = self._evidence(p, eid, "derivative:create", ctx)
        try:
            k = DerivativeKind(kind)
        except ValueError as ex:
            raise ValidationFailed("unknown derivative kind") from ex
        if not data:
            raise ValidationFailed("empty derivative")
        did = f"dv_{uuid.uuid4().hex[:20]}"
        digest = sha256_hex(data)
        key = f"{e['agency_id']}/{eid}/{did}"
        with tempfile.NamedTemporaryFile(dir=self.staging.root, delete=True) as t:
            t.write(data)
            t.flush()
            self.store.put_derivative(key, Path(t.name))
        with self.db.tx() as c:
            c.execute("INSERT INTO derivatives VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (did, eid, e["sha256"], k.value, digest, len(data), media_type, key,
                       json.dumps(params, sort_keys=True), p.sub, self.clock()))  # fmt: skip
            self.audit.append(c, _actor(p), "derivative.created", "derivative", did,
                              {"parent_evidence_id": eid, "parent_sha256": e["sha256"],
                               "kind": k.value, "sha256": digest, "params": params}, ctx=ctx)  # fmt: skip
        return {"derivative_id": did, "parent_evidence_id": eid, "parent_sha256": e["sha256"],
                "sha256": digest, "kind": k.value}  # fmt: skip

    # ---- retention & legal hold (two-person) -------------------------------------------
    def request_hold(
        self, p: Principal, eid: str, case_ref: str, reason: str, ctx: Ctx
    ) -> dict[str, Any]:
        self._evidence(p, eid, "hold:request", ctx)
        hid, now = f"lh_{uuid.uuid4().hex[:16]}", self.clock()
        with self.db.tx() as c:
            c.execute("INSERT INTO legal_holds VALUES(?,?,?,?,?,?,NULL,NULL,?,?)",
                      (hid, eid, case_ref, reason, "pending", p.sub, now, now))  # fmt: skip
            self.audit.append(c, _actor(p), "hold.requested", "evidence", eid,
                              {"hold_id": hid, "case_ref": case_ref}, ctx=ctx)  # fmt: skip
        return {"hold_id": hid, "status": "pending"}

    def approve_hold(self, p: Principal, hid: str, ctx: Ctx) -> dict[str, Any]:
        self._require(p, "hold:approve", ctx, hid)
        h = self.db.one("SELECT h.*, e.storage_key, e.version_id, e.agency_id FROM legal_holds h "
                        "JOIN evidence e USING(evidence_id) WHERE hold_id=?", (hid,))  # fmt: skip
        if not h or h["agency_id"] != p.agency:
            raise NotFound("hold not found")
        if h["requested_by"] == p.sub:
            raise Forbidden("separation of duties: requester cannot approve their own hold")
        if h["status"] != "pending":
            raise Conflict(f"hold is {h['status']}")
        self.store.set_legal_hold(h["storage_key"], h["version_id"], hid, True)
        with self.db.tx() as c:
            c.execute("UPDATE legal_holds SET status='active', approved_by=?, updated_at_ms=? "
                      "WHERE hold_id=?", (p.sub, self.clock(), hid))  # fmt: skip
            self.audit.append(c, _actor(p), "hold.approved", "evidence", h["evidence_id"],
                              {"hold_id": hid}, ctx=ctx)  # fmt: skip
        return {"hold_id": hid, "status": "active"}

    def release_hold(self, p: Principal, hid: str, reason: str, ctx: Ctx) -> dict[str, Any]:
        self._require(p, "hold:release", ctx, hid)
        h = self.db.one("SELECT h.*, e.storage_key, e.version_id, e.agency_id FROM legal_holds h "
                        "JOIN evidence e USING(evidence_id) WHERE hold_id=?", (hid,))  # fmt: skip
        if not h or h["agency_id"] != p.agency or h["status"] != "active":
            raise NotFound("active hold not found")
        if h["requested_by"] == p.sub or h["approved_by"] == p.sub:
            raise Forbidden("separation of duties: a different legal officer must release")
        self.store.set_legal_hold(h["storage_key"], h["version_id"], hid, False)
        with self.db.tx() as c:
            c.execute("UPDATE legal_holds SET status='released', released_by=?, updated_at_ms=? "
                      "WHERE hold_id=?", (p.sub, self.clock(), hid))  # fmt: skip
            self.audit.append(c, _actor(p), "hold.released", "evidence", h["evidence_id"],
                              {"hold_id": hid, "reason": reason[:300]}, ctx=ctx)  # fmt: skip
        return {"hold_id": hid, "status": "released"}

    def is_disposable(self, eid: str) -> bool:
        """Read-only policy check for the (offline) disposition process."""
        e = self.db.one("SELECT retention_until_ms FROM evidence WHERE evidence_id=?", (eid,))
        if not e:
            raise NotFound("evidence not found")
        held = self._count(
            "legal_holds", "evidence_id=? AND status IN ('pending','active')", (eid,)
        )
        return self.clock() >= e["retention_until_ms"] and held == 0

    def delete_original(self, eid: str) -> None:
        """There is deliberately no supported path; kept so the guarantee is testable."""
        e = self.db.one("SELECT storage_key FROM evidence WHERE evidence_id=?", (eid,))
        self.store.delete(e["storage_key"] if e else eid)
        raise WormViolation("unreachable")  # pragma: no cover

    # ---- alerts, fixity, custody report -----------------------------------------------
    def list_alerts(self, p: Principal, status: str, ctx: Ctx) -> list[dict[str, Any]]:
        self._require(p, "alerts:read", ctx)
        rows = self.db.query(
            "SELECT * FROM alerts WHERE status=? ORDER BY ts_ms DESC LIMIT 200", (status,)
        )
        return [{**dict(r), "detail": json.loads(r["detail_json"])} for r in rows]

    def ack_alert(self, p: Principal, aid: str, ctx: Ctx) -> dict[str, Any]:
        self._require(p, "alerts:ack", ctx, aid)
        with self.db.tx() as c:
            n = c.execute("UPDATE alerts SET status='acknowledged', acked_by=?, acked_at_ms=? "
                          "WHERE alert_id=? AND status='open'", (p.sub, self.clock(), aid)).rowcount  # fmt: skip
            if not n:
                raise NotFound("open alert not found")
            self.audit.append(c, _actor(p), "alert.acknowledged", "alert", aid, ctx=ctx)
        return {"alert_id": aid, "status": "acknowledged"}

    def run_fixity(self, limit: int = 500) -> dict[str, Any]:
        """Periodic re-hash of stored originals; detects bit-rot and out-of-band tampering."""
        rows = self.db.query("SELECT evidence_id, storage_key, version_id, sha256 FROM evidence "
                             "ORDER BY RANDOM() LIMIT ?", (limit,))  # fmt: skip
        bad = []
        for e in rows:
            with self.store.open_original(e["storage_key"], e["version_id"]) as f:
                ok = _hash_stream(f) == e["sha256"]
            if not ok:
                bad.append(e["evidence_id"])
                self._alert("FIXITY_FAILURE", "fixity_failure", e["evidence_id"],
                            {"event": "fixity_failure"})  # fmt: skip
        with self.db.tx() as c:
            self.audit.append(c, SYSTEM, "fixity.checked", "system", "fixity",
                              {"checked": len(rows), "failed": bad})  # fmt: skip
        self.metrics.inc("custody_fixity_checked_total", len(rows))
        return {"checked": len(rows), "failed": bad}

    def custody_report(self, p: Principal, eid: str, ctx: Ctx) -> dict[str, Any]:
        e = self._evidence(p, eid, "custody:report", ctx)
        derivs = [dict(d) for d in self.db.query(
            "SELECT derivative_id,kind,sha256,parent_sha256,created_by FROM derivatives "
            "WHERE parent_evidence_id=?", (eid,))]  # fmt: skip
        holds = [
            dict(h) for h in self.db.query("SELECT * FROM legal_holds WHERE evidence_id=?", (eid,))
        ]
        ids = (
            [eid, e["session_id"]]
            + [d["derivative_id"] for d in derivs]
            + [h["hold_id"] for h in holds]
        )
        trail = self.audit.for_objects(ids)
        with self.store.open_original(e["storage_key"], e["version_id"]) as f:
            current = _hash_stream(f)
        chain = self.audit.verify()
        body = {"evidence_id": eid, "generated_at_ms": self.clock(), "sha256_recorded": e["sha256"],
                "sha256_now": current, "fixity_ok": current == e["sha256"],
                "receipt": json.loads(e["receipt_json"]), "derivatives": derivs, "legal_holds": holds,
                "custody_events": trail,
                "audit_chain": {"ok": chain.ok, "entries": chain.entries, "head_hash": chain.head_hash,
                                "checkpoints_verified": chain.checkpoints_verified}}  # fmt: skip
        with self.db.tx() as c:
            self.audit.append(c, _actor(p), "custody.report.generated", "evidence", eid, ctx=ctx)
        return {
            "report": body,
            "signature": self.signer.sign_obj(body),
            "key_id": self.signer.key_id,
        }


def _hash_stream(f: Any) -> str:
    h = hashlib.sha256()
    for blk in iter(lambda: f.read(1024 * 1024), b""):
        h.update(blk)
    return h.hexdigest()


def _hash_path(p: Path) -> tuple[str, int]:
    with p.open("rb") as f:
        h, n = hashlib.sha256(), 0
        for blk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(blk)
            n += len(blk)
    return h.hexdigest(), n
