# Interview answer → implementation map

**Clarify first:** volume (chunk size/limits are config), retention & legal holds (`retention_class`, two-person holds), camera connectivity (resumable, offline-tolerant, clock-untrusted), recovery objectives (WORM + replication; RPO = replication lag).

**Capture** → `Manifest` (device, officer, capture time, sequence, case/incident, chunk hashes, object hash), Ed25519-signed.
**Upload** → chunked, resumable (`missing_chunks`), idempotency key; every chunk verified; full-file re-hash; mismatch ⇒ quarantine + alert.
**Storage** → originals write-once with retention/legal hold, derivatives separate and parent-linked (`derivatives.parent_sha256`), never replacing.
**Audit** → hash-chained append-only log of every transition and access (who/what/when/where/which version).
**Workflow** → `created → uploading → verifying → verified → available | quarantined`; ack only after durable + verified (signed receipt).
**Monitoring** → upload lag, failed chunks, mismatches, fixity, audit health (`/metrics`, `/readyz`).
**Failure-mode tests** → interrupted, duplicate, clock skew, tamper, expired credentials, storage corruption (see `tests/`); regional outage is an infrastructure test (replication/failover drill) documented in the runbook.

**Follow-up 1 — admin altering evidence?** No permission path (admin has no evidence rights; no delete/overwrite API; Object Lock COMPLIANCE; DB triggers) and any attempt raises a critical alert (`test_admin_cannot_touch_evidence_and_is_flagged`).
**Follow-up 2 — hash mismatch?** Quarantine, preserve bytes and metadata, alert, custodian disposition, mismatch recorded in the custody chain (`test_object_hash_mismatch_quarantines_and_alerts`).
