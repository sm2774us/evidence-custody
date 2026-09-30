# Runbook

**Hash mismatch / quarantined upload** — Alert `HASH_MISMATCH`. Do not delete anything. `GET /v1/uploads/{id}/inspect`, `POST /v1/uploads/{id}/triage` for the advisory. Received bytes are in `quarantine/{id}`. If transport fault: `POST /v1/quarantine/{id}/disposition {"decision":"retry_authorized"}` then the device re-uploads with a *new* idempotency key. If `integrity_inconsistency`/repeat offender: retain, inspect device, consider `POST /v1/devices/{id}/revoke`.

**`/readyz` = 503 (audit chain broken)** — Treat as a security incident. Freeze admin changes, run `custody-admin verify-audit` to find `first_bad_seq`, compare with the last anchored checkpoint, restore from replica, preserve the tampered DB.

**`FIXITY_FAILURE`** — Critical. Restore the object version from replica/Object Lock version, preserve the bad copy, run storage health checks, record findings via custody report.

**Stuck uploads** — `custody_oldest_open_upload_age_seconds` high: device offline is normal; `custody-admin expire` closes sessions past TTL.

**Bulk-access alert** — Review `evidence.accessed` reasons for the actor; ack with `POST /v1/alerts/{id}/ack`.

**Key rotation** — Rotate the service signing key by deploying a new `CUSTODY_SIGNING_KEY`; `key_id` on receipts/checkpoints identifies which key signed what. Keep old public keys for verification.

**Scheduled ops** — `custody-admin fixity && checkpoint && scan && verify-audit` every 6h (see CronJob). Export checkpoints to the anchors bucket.
