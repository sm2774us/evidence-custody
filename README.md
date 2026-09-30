# Evidence Custody

Body-camera footage ingest with a **cryptographic chain of custody** — a reference implementation of the
"Design a Body-Camera Footage Upload Path with Chain of Custody" problem, built the way a
public-safety platform team would ship it: signed at capture, resumable and idempotent in transit,
verified before acknowledgement, immutable at rest, and accountable in an append-only audit trail.

```
camera ──sign manifest──▶ POST /v1/uploads ──▶ PUT chunks (verified each) ──▶ POST complete
                                                            │
                          re-hash whole object ── mismatch ─┴─▶ QUARANTINE + alert + custody record
                                   │ match
                     write-once original (WORM) ─▶ read-back re-hash ─▶ signed receipt ─▶ AVAILABLE
```

| Requirement (from the design answer) | Where it lives | Proven by |
|---|---|---|
| Immutable capture metadata, SHA-256 per chunk + whole object | `models.py`, `device.py` (Ed25519-signed manifest) | `test_ingest`, interop vector |
| Chunked, resumable, idempotent upload | `service.create_upload/put_chunk`, `client.py`, `sdk-ts` | `test_resume_*`, `test_duplicate_*` |
| Verify every chunk, recompute full hash, quarantine on mismatch | `service.complete/_quarantine` | `test_object_hash_mismatch_*` |
| Originals in write-once storage, retention + legal hold; derivatives never replace | `storage.py`, `service.create_derivative/*hold*` | `test_originals_are_write_once_*`, `test_derivatives_*` |
| Append-only, hash-chained audit of every transition and access | `audit.py` (+ DB triggers, signed checkpoints) | `test_audit_tamper_*`, `test_truncation_*` |
| RBAC, least privilege, separation of duties | `auth.py`, `service.py` | `test_admin_cannot_*`, `test_separation_of_duties_*` |
| Acknowledge only after durable + verified | signed receipt, read-after-write verify | `test_happy_path_*` |
| Monitoring: lag, failed chunks, mismatches, durability, audit health | `/metrics`, `/readyz`, fixity job | `test_endpoints_*`, `test_fixity_*` |
| Failure modes: interrupts, duplicates, clock skew, tamper, expired creds | fault-injecting client + tests | see `tests/` |

Beyond the brief: device-signed manifests (non-repudiation), signed receipts (camera purges only on a
verified receipt), sequence-gap/replay detection, two-person device activation and legal holds,
periodic **fixity** re-hashing, signed **custody reports**, anomaly alerts on access patterns,
**AI-assisted triage that can never gate the workflow**, a read-only **MCP server**, a TypeScript SDK
with a cross-language signature test, Terraform for S3 Object Lock (COMPLIANCE), hardened
Docker/Kubernetes, and a CI/CD pipeline with signing, SBOM and provenance.

## Quick start
```bash
# Linux / WSL Ubuntu (native)                     # Windows 11: see WALKTHROUGH.md (Docker Desktop)
bash scripts/setup-linux.sh --install            # one time: Python 3.12+, Node 22, git, make
bash scripts/check.sh                            # ruff, mypy, pytest, evals, SDK, web console
bash scripts/dev.sh                              # API :8080 + Evidence Console :5173 (hot reload)
bash scripts/dev-token.sh auditor                # a login token for the console

# Anywhere Docker runs
cp .env.example .env && docker compose up -d --build   # API :8080, console http://localhost:8081
docker compose run --rm api custody-admin demo         # flaky network + corruption + tamper + custody report
```

## Evidence Console (web)
A production-minded React 19 + TypeScript front end in `web/`, talking only to the existing API:
sign-in with a scoped bearer token, an **assistant** that turns plain requests into permission-checked
API calls (works with no AI), dashboard, evidence viewer with **in-browser SHA-256 and Ed25519
verification**, upload/quarantine review, alerts, audit-log browser, device management.
Stack: Vite, Tailwind 4, shadcn/ui-style components on Radix, TanStack Query/Table/Router, Zustand, Motion.
Ships as a non-root nginx image with a strict CSP and a same-origin API proxy, and has its own CI gate
(lint, types, tests with coverage floor, build) plus a compose-based full-stack smoke test.
Design, screens and requirements: `docs/Solution-Deep-Dive.md`, `docs/SRS.md`, `docs/SRS-Compliance.md`.

## AI, where it earns its place — and nowhere else
* **Incident triage** (`triage.py`): deterministic rules produce the advisory; an LLM *optionally* adds a
  plain-language summary and extra whitelisted actions. It sees minimized pseudonymous metadata only
  (never bytes, names or device free-text), can raise but never lower severity, cannot change the
  category, and its model id + prompt hash are audited. Outage or garbage output ⇒ silent fallback.
* **Evals** (`evals/`): a golden set, including a prompt-injection case, runs deterministically in every
  CI build; `ai-evals.yml` scores a real model weekly and on triage changes.
* **MCP** (`mcp_server.py`): read-only tools for an operations copilot. No write/download/delete.
* Quarantine, acceptance and acknowledgement are decided **only** by hashes and signatures.

## Layout
`src/custody` service · `web` Evidence Console (React) · `sdk-ts` Node/TS SDK · `evals` triage golden set · `deploy` Terraform + k8s ·
`scripts` Windows + Linux/WSL helpers · `docs` architecture, threat model, CJIS mapping, runbook, deep dive, SRS · `.github/workflows` CI, security, AI evals, release.

## Status and honest limits
See `docs/ARCHITECTURE.md#known-limits`. Notably: metadata store is SQLite (single writer; PostgreSQL adapter is the
scale-out path), dev tokens stand in for OIDC/mTLS, and the S3 adapter is unit-tested against a stub —
run it against a real Object-Lock bucket in your environment before relying on it. This is a reference
implementation, not a certified CJIS system; compliance is an organizational program (see `docs/COMPLIANCE.md`).
