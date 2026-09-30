# CJIS / evidence-integrity control mapping (engineering view)

Not a certification. CJIS Security Policy compliance also depends on personnel screening, facility, agency
policy and the hosting environment. This maps what the *software* provides to the policy areas.

| Policy area | Implementation |
|---|---|
| Access control (5.5) | RBAC least privilege, agency scoping, separation of duties, reason-for-access |
| Auditing & accountability (5.4) | Hash-chained audit of auth, access, state change, admin actions; signed checkpoints; verify endpoint |
| Identification & authentication (5.6) | Short-lived tokens, revocation; production: OIDC + MFA, mTLS for devices |
| Encryption (5.10) | TLS in transit (gateway); SSE-KMS at rest (Terraform); FIPS-validated crypto modules are a deployment choice |
| Media protection / integrity (5.8, 5.10) | WORM originals, fixity, read-after-write verification |
| Incident response (5.3) | Alerts with triage advisories, quarantine dispositions, runbook |
| Configuration & supply chain | Constrained deps, image scan, SBOM, keyless signing, provenance |
| Privacy | AI sees minimized metadata only; no CJI in CI, tests or prompts |
