# Software Requirements Specification: Evidence Console (web front end)

| | |
|---|---|
| **Product** | Evidence Console, the browser client of the Evidence Custody service |
| **Version** | 1.0 (feature branch `feature/linux-workflow-and-web-console`) |
| **Status** | Baseline for review |
| **Companions** | `Solution-Deep-Dive.md` (design and wireframes), `SRS-Compliance.md` (evidence), `ARCHITECTURE.md`, `THREAT_MODEL.md` |

Keywords **MUST**, **SHOULD**, **MAY** follow RFC 2119. Priority: **M** = must, **S** = should, **C** = could. Source: **BR** business rule of the custody service, **SEC** security principle, **UX** usability, **OPS** operations, **DEV** developer workflow.

---

## 1. Introduction

### 1.1 Purpose
Define what the Evidence Console must do and how well, so it can be built, verified and accepted independently of the people who wrote it.

### 1.2 Scope
The console is a single-page web application that lets authorised staff operate the existing custody API: monitor integrity, review alerts and quarantined uploads, retrieve and verify evidence, produce custody reports, place legal holds, manage camera identities and browse the audit log. It adds **no server-side logic**; it consumes the API in `src/custody/app.py` unchanged.

Also in scope: the container image that serves it, its CI/CD pipeline, and the Linux/WSL developer workflow delivered with it.
Out of scope: the camera-side uploader, the API itself, identity-provider integration, native mobile apps, and any AI model hosting.

### 1.3 Definitions
| Term | Meaning |
|---|---|
| API | The FastAPI custody service |
| Token | Signed bearer credential carrying subject, role, agency and expiry |
| Role | One of `device`, `reader`, `custodian`, `legal`, `auditor`, `admin` |
| Intent | A user request the Assistant recognises (`status`, `alerts`, ...) |
| Card | The structured rendering of one Assistant answer |
| Fixity | Equality of stored bytes with the attested SHA-256 |
| Mutating action | Any request that writes state (POST) |

### 1.4 References
`docs/ARCHITECTURE.md`, `docs/THREAT_MODEL.md`, `docs/COMPLIANCE.md`, `docs/RUNBOOK.md`; OWASP ASVS 4.0; WCAG 2.2 (AA); RFC 2119; FIPS 180-4 (SHA-256); RFC 8032 (Ed25519); the stack description in `MODERN_UI_UX_STACK.md`.

### 1.5 Overview
Section 2 describes the product; section 3 lists requirements by area; section 4 the external interfaces; section 5 data; section 6 verification; appendices give the permission matrix and the API traceability.

---

## 2. Overall description

### 2.1 Product perspective
```
Browser (SPA) --same origin--> nginx --/v1,/readyz,/healthz,/metrics--> Custody API --> WORM store + metadata DB
```
The SPA is stateless apart from tab-scoped browser storage. The API remains the sole authority for authentication, authorisation, integrity and audit.

### 2.2 User classes
| Class | Role(s) | Primary goals |
|---|---|---|
| Evidence custodian | `custodian` | Resolve quarantines, request holds, add derivatives, produce reports |
| Auditor | `auditor` | Verify the chain, review alerts and the audit log |
| Evidence consumer | `reader` | Retrieve and verify recordings |
| Legal officer | `legal` | Approve and release holds, read custody reports |
| Administrator | `admin` | Enrol, activate and revoke cameras; sign audit checkpoints |
| Developer / operator | n/a | Build, test, deploy, run locally on Windows, Ubuntu or WSL |

### 2.3 Operating environment
Evergreen desktop browsers supporting ES2022 and WebCrypto SHA-256 (Ed25519 verification additionally needs a browser with Ed25519 in WebCrypto). Phones are supported for reading and light actions. Runtime: Linux container (nginx unprivileged, port 8080). Build: Node 22. Development hosts: Windows 11 with Docker Desktop, Ubuntu 24.04, WSL2 Ubuntu.

### 2.4 Constraints
C1 The API contract is fixed; the console MUST NOT require API changes (one optional CLI seeding command was added outside the API).
C2 UI stack: React 19, TypeScript, Tailwind, shadcn/ui-style components on Radix, TanStack Query/Table/Router, Zustand, Motion.
C3 No third-party runtime origins (scripts, fonts, analytics).
C4 The API offers no list/search endpoints; lookups are by ID.

### 2.5 Assumptions and dependencies
A1 Tokens are issued out of band (CLI now, identity provider later). A2 TLS terminates at the ingress. A3 The API's clock is authoritative for expiry; the browser clock is used only for display and early warning. A4 A user's browser is not trusted to enforce policy.

---

## 3. Specific requirements

### 3.1 Access and session (FR-AUTH)
| ID | Requirement | Pri | Source |
|---|---|---|---|
| FR-AUTH-01 | The console MUST require a bearer token before showing any application screen; unauthenticated navigation MUST redirect to sign-in. | M | SEC |
| FR-AUTH-02 | Sign-in MUST decode the token locally and reject malformed tokens and tokens whose expiry has passed, without sending a request. | M | UX |
| FR-AUTH-03 | Before submission, sign-in SHOULD preview subject, role, agency, expiry and permissions. | S | UX |
| FR-AUTH-04 | The token MUST be held only in `sessionStorage` (never `localStorage`, cookies or URLs). | M | SEC |
| FR-AUTH-05 | Sign-out, token expiry and any `401` response MUST clear the token, the chat history and the query cache and return to sign-in with the reason shown. | M | SEC |
| FR-AUTH-06 | The top bar MUST show remaining session time, MUST warn once when under two minutes remain, and MUST sign out at zero. | M | UX |
| FR-AUTH-07 | Navigation MUST show only items permitted to the user's role. This is a convenience; the server remains authoritative. | M | SEC |
| FR-AUTH-08 | Sign-in MUST display service reachability and audit-chain state before authentication. | S | OPS |

### 3.2 Dashboard (FR-DASH)
| ID | Requirement | Pri | Source |
|---|---|---|---|
| FR-DASH-01 | The dashboard MUST show evidence stored, open alerts, quarantined uploads and oldest open upload age, derived from `/metrics` and `/v1/alerts`. | M | OPS |
| FR-DASH-02 | Values MUST refresh automatically (at most every 30 s) and on window focus. | M | OPS |
| FR-DASH-03 | When `/readyz` reports an audit failure, a prominent banner MUST appear instructing the user to treat it as an incident. | M | BR |
| FR-DASH-04 | Users holding `audit:verify` MUST be able to run chain verification and see the outcome. | M | BR |
| FR-DASH-05 | Users holding `audit:checkpoint` MUST be able to request a signed checkpoint. | S | BR |
| FR-DASH-06 | A role lacking `alerts:read` MUST see an explanation instead of an empty list. | S | UX |

### 3.3 Assistant (FR-ASST)
| ID | Requirement | Pri | Source |
|---|---|---|---|
| FR-ASST-01 | The Assistant MUST accept plain-language requests and map them deterministically to intents: help, status, alerts, verify, scan, checkpoint, evidence, custody, upload, triage, ack, gaps. | M | UX |
| FR-ASST-02 | The Assistant MUST function with no AI model or network service beyond the custody API. | M | BR |
| FR-ASST-03 | Before calling the API, the Assistant MUST check the user's role and, if lacking, answer with the missing capability without issuing the request. | M | SEC |
| FR-ASST-04 | Answers MUST be rendered as typed cards containing only data returned by the API. Unrecognised input MUST yield suggestions, not a guessed action. | M | SEC |
| FR-ASST-05 | Any state-changing action reachable from a card MUST require a second explicit confirming click. | M | SEC |
| FR-ASST-06 | The transcript MUST be capped (40 messages), stored per tab, exclude in-flight messages, and be discarded at sign-out. | M | SEC |
| FR-ASST-07 | The composer MUST support Enter to send, Shift+Enter for newline, and ↑ to recall previous messages. | S | UX |
| FR-ASST-08 | Assistant output MUST be announced to assistive technology (`role="log"`, polite live region). | M | ACC |
| FR-ASST-09 | Every card that names an object MUST link to the relevant full screen. | S | UX |

### 3.4 Evidence (FR-EVID)
| ID | Requirement | Pri | Source |
|---|---|---|---|
| FR-EVID-01 | Users MUST be able to open evidence by ID; malformed IDs MUST be rejected inline before any request. | M | UX |
| FR-EVID-02 | The overview MUST show hash, size, media type, case, device, officer, sequence, both clocks, retention and storage version. | M | BR |
| FR-EVID-03 | Retrieval MUST require a reason of at least eight characters, sent as `X-Access-Reason`. | M | BR |
| FR-EVID-04 | After retrieval the console MUST compute SHA-256 in the browser and compare it with the attested hash (and the response header when present). | M | BR |
| FR-EVID-05 | On mismatch the console MUST show an unambiguous failure and MUST NOT offer preview or save. | M | BR |
| FR-EVID-06 | Files larger than 256 MiB MUST NOT be retrieved in the browser; the user MUST be directed to the SDK or CLI. | M | OPS |
| FR-EVID-07 | Object URLs created for previews MUST be released on replacement and unmount. | S | SEC |
| FR-EVID-08 | The console MUST generate a custody report on demand and display fixity, audit-chain status and signature status as three independent indicators. | M | BR |
| FR-EVID-09 | The console MUST verify the report's Ed25519 signature in the browser using the key from `/v1/keys`. If the browser cannot, it MUST say so and MUST NOT show "valid". | M | SEC |
| FR-EVID-10 | Users MUST be able to export the signed report as JSON. | S | BR |
| FR-EVID-11 | Users with the relevant permission MUST be able to request, approve and release legal holds; approvals and releases MUST use two-click confirmation. | M | BR |
| FR-EVID-12 | Users with `derivative:create` MUST be able to attach a derivative of a chosen kind. | S | BR |
| FR-EVID-13 | Recently opened IDs (max 12) SHOULD be offered for quick return and clearable by the user. | C | UX |
| FR-EVID-14 | The active tab MUST be part of the URL. | S | UX |

### 3.5 Uploads and quarantine (FR-UPL)
| ID | Requirement | Pri | Source |
|---|---|---|---|
| FR-UPL-01 | Users with `upload:inspect` MUST be able to inspect an upload by session ID. | M | OPS |
| FR-UPL-02 | The console MUST show the state progression, received vs missing chunks and any failure reason. | M | OPS |
| FR-UPL-03 | While the state is `created`, `uploading` or `verifying`, the view SHOULD poll every 3 s and stop when settled. | S | UX |
| FR-UPL-04 | For quarantined uploads, users with `triage:run` MUST be able to request an advisory and see whether it came from rules alone or rules plus AI. | M | BR |
| FR-UPL-05 | Advisory text MUST be labelled advisory-only and MUST NOT drive any state change. | M | BR |
| FR-UPL-06 | Users with `quarantine:review` MUST be able to record one of two decisions with a note of at least eight characters, after a confirming click. | M | BR |
| FR-UPL-07 | The event history for the session MUST be sortable, filterable and paged. | S | UX |

### 3.6 Alerts (FR-ALRT)
| ID | Requirement | Pri | Source |
|---|---|---|---|
| FR-ALRT-01 | Users with `alerts:read` MUST see open and acknowledged alerts in a sortable, filterable table; severity sorts critical first. | M | OPS |
| FR-ALRT-02 | A row MUST open a detail view with summary, reasons, recommended actions, source and object. | M | UX |
| FR-ALRT-03 | Users with `alerts:ack` MUST be able to acknowledge with two-click confirmation. | M | BR |
| FR-ALRT-04 | The list SHOULD refresh at least every 30 s. | S | OPS |

### 3.7 Audit log (FR-AUD)
| ID | Requirement | Pri | Source |
|---|---|---|---|
| FR-AUD-01 | Users with `audit:read` MUST be able to page through the log, filter and sort, and open an entry to see all fields including previous and entry hashes and request ID. | M | BR |
| FR-AUD-02 | The console MUST state clearly whether all entries have been loaded. | M | UX |
| FR-AUD-03 | Users with `audit:verify` MUST be able to verify the chain; users with `audit:scan` MUST be able to run an anomaly scan. | M | BR |
| FR-AUD-04 | Denied and quarantine events SHOULD be visually distinguished. | C | UX |

### 3.8 Devices (FR-DEV)
| ID | Requirement | Pri | Source |
|---|---|---|---|
| FR-DEV-01 | Administrators MUST be able to register a device with validated ID, 64-hex public key and officer ID. | M | BR |
| FR-DEV-02 | Administrators MUST be able to activate and revoke a device with two-click confirmation; server refusals (e.g. same-person activation) MUST be shown. | M | BR |
| FR-DEV-03 | Users with `evidence:read` MUST be able to check a device for sequence gaps. | S | BR |

### 3.9 Settings (FR-SET)
| ID | Requirement | Pri | Source |
|---|---|---|---|
| FR-SET-01 | Users MUST be able to choose dark, light or system theme; the choice MUST persist. | S | UX |
| FR-SET-02 | Settings MUST display identity, agency, expiry, permissions, and the service key ID and public key. | S | SEC |

### 3.10 Non-functional requirements
**Security (NFR-SEC)**
| ID | Requirement | Pri |
|---|---|---|
| NFR-SEC-01 | The SPA MUST call only its own origin. | M |
| NFR-SEC-02 | The serving tier MUST send CSP (`default-src 'self'`, no inline script, `frame-ancestors 'none'`), `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, `Cross-Origin-Opener-Policy` on every response class. | M |
| NFR-SEC-03 | Source MUST NOT use raw-HTML injection; this MUST be lint-enforced. | M |
| NFR-SEC-04 | The runtime image MUST run as non-root with all capabilities dropped. | M |
| NFR-SEC-05 | Evidence bytes MUST NOT be persisted by the application. | M |
| NFR-SEC-06 | Dependencies MUST be locked, installed with `npm ci --ignore-scripts`, and audited in CI. | M |
| NFR-SEC-07 | Client authorisation checks MUST NOT be relied upon for security. | M |

**Reliability and fault tolerance (NFR-REL)**
| ID | Requirement | Pri |
|---|---|---|
| NFR-REL-01 | Every request MUST have a timeout (15 s default; longer for content, derivatives, reports). | M |
| NFR-REL-02 | Network failures and `5xx` MUST be retried at most twice with backoff; `4xx` MUST NOT be retried. | M |
| NFR-REL-03 | An uncaught render error MUST show a recovery screen instead of a blank page. | M |
| NFR-REL-04 | Loss of connectivity MUST be signalled by a banner and an "API unreachable" indicator. | M |
| NFR-REL-05 | Errors MUST show the server's request ID when available. | S |
| NFR-REL-06 | A 503 from `/readyz` MUST be interpreted as an audit-integrity failure, not a generic outage. | M |
| NFR-REL-07 | Failure of `/metrics` MUST degrade the dashboard, not break it. | S |

**Usability and accessibility (NFR-UX)**
| ID | Requirement | Pri |
|---|---|---|
| NFR-UX-01 | The UI SHOULD conform to WCAG 2.2 AA: keyboard operable, visible focus, semantic landmarks, skip link, labelled controls, `aria-sort`, live regions. | S |
| NFR-UX-02 | Text and status colours SHOULD meet 4.5:1 contrast in both themes; status MUST NOT rely on colour alone. | S |
| NFR-UX-03 | Animation MUST honour the reduced-motion preference. | M |
| NFR-UX-04 | Layout MUST adapt from 360 px to desktop without horizontal page scroll. | S |
| NFR-UX-05 | Destructive or state-changing actions MUST be visibly distinct and confirmed. | M |

**Performance (NFR-PERF)**
| ID | Requirement | Pri |
|---|---|---|
| NFR-PERF-01 | The initial JavaScript payload SHOULD stay under 250 kB gzip; the build MUST warn above 800 kB raw. | S |
| NFR-PERF-02 | Hashed assets MUST be cacheable for a year; `index.html` MUST NOT be cached. | M |
| NFR-PERF-03 | Streaming responses (evidence, derivatives) MUST NOT be buffered by the proxy. | M |

**Maintainability and delivery (NFR-DEV)**
| ID | Requirement | Pri |
|---|---|---|
| NFR-DEV-01 | Lint, strict type-check, tests and build MUST gate merges through the existing `ci-ok` check. | M |
| NFR-DEV-02 | Logic folders MUST meet a coverage floor enforced in CI. | M |
| NFR-DEV-03 | The API contract with the client (canonical JSON, signatures) MUST be tested against the Python service's vectors. | M |
| NFR-DEV-04 | A full-stack CI job MUST start API and console and probe the proxy. | S |
| NFR-DEV-05 | Releases MUST publish signed console images with provenance. | S |
| NFR-DEV-06 | The project MUST be buildable, testable and runnable on Windows 11 (Docker) and on Ubuntu/WSL (native or Docker) with equivalent documented steps. | M |
| NFR-DEV-07 | No bot may open branches or pull requests. | M |

### 3.11 Linux / WSL workflow (FR-LNX)
| ID | Requirement | Pri | Source |
|---|---|---|---|
| FR-LNX-01 | Provide a prerequisite checker with an opt-in installer for Ubuntu/Debian/WSL. It MUST change nothing unless asked. | M | DEV |
| FR-LNX-02 | Provide one command running every CI check natively, and an option to run them in containers. | M | DEV |
| FR-LNX-03 | Provide one command starting API and console for development with persistent development secrets excluded from version control. | M | DEV |
| FR-LNX-04 | Provide a token helper and an owner-substitution helper equivalent to the Windows ones. | M | DEV |
| FR-LNX-05 | Scripts MUST warn when a WSL checkout resides on the Windows drive. | S | DEV |
| FR-LNX-06 | The Windows workflow MUST remain unchanged in behaviour. | M | DEV |
| FR-LNX-07 | Provide a sample-data command for a running server. | S | DEV |
| FR-LNX-08 | `WALKTHROUGH.md` and `README.md` MUST document both paths. | M | DEV |

---

## 4. External interface requirements

### 4.1 User interface
Screens S01 to S20 as drawn in `Solution-Deep-Dive.md` §10. Design tokens in §9 of that document are normative for colour, spacing and type.

### 4.2 API consumed (all JSON unless stated; errors `{ "error", "message", ...}`)
| Method and path | Used by | Permission |
|---|---|---|
| `GET /readyz` | status pill, sign-in, dashboard, assistant | none |
| `GET /metrics` (text) | dashboard, assistant | none |
| `GET /v1/keys` | settings, report verification | none |
| `GET /v1/alerts?status=` · `POST /v1/alerts/{id}/ack` | alerts, dashboard, assistant | `alerts:read` · `alerts:ack` |
| `GET /v1/audit?after&limit` | audit log | `audit:read` |
| `POST /v1/audit/verify` · `/scan` · `/checkpoint` | audit, dashboard, assistant | `audit:verify` · `audit:scan` · `audit:checkpoint` |
| `GET /v1/evidence/{id}` | evidence, assistant | `evidence:read` |
| `GET /v1/evidence/{id}/content` (+ `X-Access-Reason`) | access tab | `evidence:download` |
| `GET /v1/evidence/{id}/custody` | custody tab, assistant | `custody:report` |
| `POST /v1/evidence/{id}/derivatives?kind=` | holds and derivatives tab | `derivative:create` |
| `POST /v1/evidence/{id}/holds` · `/v1/holds/{id}/approve` · `/release` | holds and derivatives tab | `hold:request` · `hold:approve` · `hold:release` |
| `GET /v1/uploads/{id}/inspect` · `POST /v1/uploads/{id}/triage` | upload detail, assistant | `upload:inspect` · `triage:run` |
| `POST /v1/quarantine/{id}/disposition` | upload detail | `quarantine:review` |
| `POST /v1/devices` · `.../activate` · `.../revoke` · `GET .../sequence-gaps` | devices, assistant | `device:*` · `evidence:read` |

Every request carries `Authorization: Bearer`, `credentials: omit`, `cache: no-store`.

### 4.3 Software interfaces
Browser WebCrypto (`SHA-256`, `Ed25519`); `sessionStorage`, `localStorage` (preferences only); nginx `envsubst` template (`API_UPSTREAM`); GitHub Actions; Docker Compose.

### 4.4 Communications
HTTPS at ingress; HTTP/1.1 between nginx and API; nginx adds `X-Request-ID`.

---

## 5. Data requirements
| Data | Location | Retention |
|---|---|---|
| Token, decoded identity | `sessionStorage` `console-session` | tab lifetime |
| Assistant transcript (metadata only) | `sessionStorage` `console-chat` | tab lifetime, max 40 |
| Theme, recent IDs (max 12) | `localStorage` `console-prefs` | until cleared |
| API responses | TanStack Query memory | cleared at sign-out |
| Evidence bytes | memory (Blob / object URL) | until replaced or unmount |

No personal data is written to disk by the console. Recent IDs are opaque identifiers.

---

## 6. Verification approach
| Method | Applies to |
|---|---|
| **T** Automated test (Vitest, Testing Library) | FR-AUTH-01..05, FR-ASST-01..06, FR-EVID-09, NFR-REL-01..02, 06, NFR-DEV-03 and others as mapped in `SRS-Compliance.md` |
| **A** Static analysis (ESLint, `tsc --strict`) | NFR-SEC-03, type safety |
| **I** Inspection of code and configuration | most UI behaviours, NFR-SEC-02, 04 |
| **D** Demonstration against a running stack | proxy behaviour, headers, end-to-end |
| **CI** Executed by GitHub Actions | NFR-DEV-01, 04, 05, container builds |
| **M** Manual / external audit | WCAG conformance, cross-browser behaviour, visual fidelity |

---

## Appendix A: Permission matrix (mirrors `src/custody/auth.py`)
| Permission | reader | custodian | legal | auditor | admin | device |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| evidence:read | X | X | X | X | | |
| evidence:download | X | X | | | | |
| derivative:create | | X | | | | |
| hold:request | | X | | | | |
| hold:approve, hold:release | | | X | | | |
| quarantine:review, upload:inspect | | X | | inspect only | | |
| triage:run | | X | | X | | |
| custody:report | | X | X | X | | |
| alerts:read, alerts:ack | | X | | X | | |
| audit:read, audit:verify, audit:scan | | | | X | | |
| audit:checkpoint | | | | | X | |
| device:register, activate, revoke | | | | | X | |
| upload:create, write, read | | | | | | X |

## Appendix B: Requirement-to-screen index
FR-AUTH → S01, S02 · FR-DASH → S04 · FR-ASST → S05, S03 · FR-EVID → S06 to S10 · FR-UPL → S11 to S13 · FR-ALRT → S14, S15 · FR-AUD → S16, S17 · FR-DEV → S18 · FR-SET → S19 · NFR-REL, NFR-UX → S20.
