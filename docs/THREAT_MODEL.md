# Threat model (STRIDE-oriented)

| Threat | Control | Detection |
|---|---|---|
| Spoofed device / forged metadata | Ed25519 manifest signature vs registered key; two-person activation | `SIGNATURE_INVALID` critical alert |
| Bytes altered in transit | Per-chunk SHA-256 vs signed manifest; whole-object re-hash | `chunk.rejected`, `HASH_MISMATCH` |
| Replay / substitution | `(device, sequence_no)` uniqueness; idempotency-key binding | `SEQUENCE_CONFLICT`, `IDEMPOTENCY_CONFLICT` |
| Insider admin edits evidence | Admin role has no evidence permissions; WORM + Object Lock COMPLIANCE; no delete path | Admin attempt ⇒ critical alert; audit |
| DBA rewrites audit log | Append-only triggers/REVOKE; hash chain; signed checkpoints anchored off-box | `/readyz` 503, `verify-audit`, scheduled job |
| Silent storage corruption | Read-after-write verify; periodic fixity | `FIXITY_FAILURE` |
| Bulk exfiltration / snooping | Mandatory access reason; per-actor rate rules; agency scoping | `BULK_EVIDENCE_ACCESS`, `REPEATED_AUTHZ_DENIALS` |
| Cross-agency access | Agency claim on every query; cross-agency returns as denial + audit | `authz.denied` |
| Stolen/expired credential | Short TTL, revocation list (`jti`), device revocation | 401s, metrics |
| Device clock manipulation | Server time authoritative; future-skew flag | `CLOCK_FUTURE_CAPTURE` |
| Prompt injection via metadata | Allow-list minimization; JSON envelope; schema-validated output; deterministic floor | `evals/cases.jsonl` injection case |
| Repudiation | Signed manifests, receipts, reports, checkpoints; actor+IP+request-id on every audit row | custody report |
| DoS via huge/never-finished uploads | Size/chunk limits, session TTL + expiry job, upload-lag metric | `custody_oldest_open_upload_age_seconds` |
