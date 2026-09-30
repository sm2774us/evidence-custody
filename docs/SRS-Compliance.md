# SRS Compliance Report: Evidence Console

| | |
|---|---|
| **Subject** | Web console, serving image, CI additions and Linux/WSL scripts on branch `feature/linux-workflow-and-web-console` |
| **Measured against** | `docs/SRS.md` v1.0 (94 requirements) |
| **Method** | Requirement-by-requirement review of code and configuration, automated results from this authoring environment, and direct exercise of the nginx tier and the developer scripts against a live API |
| **Not verified** | Anything needing Docker, GitHub Actions, a real browser, a screen reader, Windows or WSL. See §5 |

## 1. Executive summary

* **The logic layer is verified; the screens are mostly not.** Token handling, the API client, the assistant, stores, canonical JSON and Ed25519/SHA-256 primitives have direct tests, including a **cross-language signature check against the Python service's own vector**. The nine page components are implemented and type-checked, but only sign-in, the dashboard shell, role-filtered navigation and the integrity-failure indicator have integration tests. Most page behaviours are therefore rated 🟡, not ✅.
* **Delivery tier verified locally:** the nginx template was rendered and exercised against the real API (SPA fallback, proxy, 401 passthrough, cache rules, six security headers on every route class, request-ID propagation).
* **Linux workflow verified on Ubuntu 24.04:** full native check, dev stack, token and owner helpers, seed command. WSL, `--install` and `--docker` were not run.
* **Written but never executed:** the container image build, the compose `stack` job, the extended `ci.yml`, `security.yml` and `release.yml`, and everything Windows.
* **Not met / not attempted:** automated accessibility scanning, real-browser end-to-end tests, visual regression, cross-browser testing.
* **Wireframes are drawings in Markdown, not Figma files.** They were derived from the code and have not been compared with a rendered screen.

### Tally
| Status | Count |
|---|---:|
| ✅ Met | 27 |
| 🟡 Met in code, unverified here | 63 |
| 🟠 Partially met | 4 |
| ❌ Not met | 0 |
| **Total** | **94** |

### Status legend
✅ **Met**: implemented and covered by a check that ran green here (test, static analysis, measurement or live demonstration).
🟡 **Met in code, unverified here**: implemented; needs a browser, Docker, CI run or human review to confirm.
🟠 **Partially met**: implemented with a stated gap.
❌ **Not met / not delivered.**

### Evidence that ran green
| Check | Result |
|---|---|
| Python: ruff check and format, mypy strict | 0 issues |
| Python tests | 46 passing (45 existing + seed), coverage 93 % against an 88 % gate |
| Triage evals (rules) | 13 / 13 |
| Web: ESLint (React-hooks rules, raw-HTML ban), `tsc --strict` with `noUncheckedIndexedAccess` | 0 errors |
| Web: Vitest | **54 passing** in 7 files; coverage of `lib`, `assistant`, `store` 82.9 % lines / 84.4 % statements / 78.3 % functions / 77.6 % branches against 80/80/75/70 gates |
| Web: production build | JS 726 kB raw, **224.7 kB gzip**; CSS 34 kB raw, 6.7 kB gzip |
| `npm audit --audit-level=high` (web) | 0 vulnerabilities |
| `bash scripts/check.sh --native` (Ubuntu 24.04, Python 3.12, Node 22) | passed end to end before the last edits; components re-run individually after them |
| nginx 1.24 with the rendered template, in front of the live API | routes, proxy, 401, headers, cache rules as in §3.10 |
| `dev.sh`, `dev-token.sh`, `set-owner.sh`, `custody-admin seed` | worked as described |
| `actionlint` on all workflows | clean (re-run after final edits, see §5) |

## 2. Traceability to the request

| Request | Delivered | Status |
|---|---|---|
| Keep the Windows 11 workflow as is | Unchanged, except a web step appended to `check.cmd` | 🟡 (not run on Windows) |
| Alternate Ubuntu / WSL workflow: scripts and docs | `scripts/*.sh`, `WALKTHROUGH.md` Part 10, `README.md`, Makefile | ✅ Ubuntu · 🟠 WSL |
| Realistic, minimal, production-grade front end, chat-like or better | Assistant plus dashboard and task screens | ✅ built · 🟡 production-readiness |
| Use the supplied UI stack | React 19, TS, Tailwind 4, shadcn-style on Radix, TanStack Query/Table/Router, Zustand, Motion | ✅ |
| Work with existing APIs seamlessly | No API change; one CLI command added for sample data | ✅ against fakes and live proxy · 🟡 in a real browser |
| Automated GitHub CI/CD | `web` and `stack` jobs, release of a signed web image, npm audit | 🟡 |
| Update WALKTHROUGH and README | Done | ✅ |
| `docs/` with Solution-Deep-Dive, SRS, SRS-Compliance, similar to but not the same as the references | Done; different structure, subject and diagram style | ✅ |
| Wireframes of every screen with purpose, role and features | 20 artboards (S01 to S20) | ✅ delivered · 🟠 fidelity (ASCII, not rendered) |

## 3. Requirement-level compliance

### 3.1 Access and session

| ID | Status | Evidence or gap |
|---|:-:|---|
| FR-AUTH-01 | ✅ | `app.test` anonymous redirect to sign-in |
| FR-AUTH-02 | ✅ | `app.test` bad token rejected; `store.test` malformed and expired tokens |
| FR-AUTH-03 | ✅ | `app.test` identity preview appears after pasting a token |
| FR-AUTH-04 | ✅ | `store.test` token only in `sessionStorage`, absent from `localStorage` |
| FR-AUTH-05 | ✅ | `api.test` 401 signs out; `store.test` chat wiped; `main.tsx` clears cache (inspection) |
| FR-AUTH-06 | 🟡 | Countdown, warning and auto sign-out implemented in `AppShell`; no timer test |
| FR-AUTH-07 | ✅ | `app.test` reader menu excludes Audit log, Alerts, Uploads |
| FR-AUTH-08 | 🟡 | Implemented in `LoginPage`; not asserted by a test |

### 3.2 Dashboard

| ID | Status | Evidence or gap |
|---|:-:|---|
| FR-DASH-01 | 🟡 | Implemented; test asserts page load and alert row, not every KPI |
| FR-DASH-02 | 🟡 | `refetchInterval` 15/30 s and focus refetch by configuration; not timed in a test |
| FR-DASH-03 | ✅ | `app.test` 503 on `/readyz` produces the integrity-failure indicator |
| FR-DASH-04 | 🟡 | Implemented; no test |
| FR-DASH-05 | 🟡 | Implemented; no test |
| FR-DASH-06 | 🟡 | Implemented; no test |

### 3.3 Assistant

| ID | Status | Evidence or gap |
|---|:-:|---|
| FR-ASST-01 | ✅ | `assistant.test` 24 parsing cases across all 12 intents |
| FR-ASST-02 | ✅ | No model or extra network call exists in `assistant/`; `assistant.test` runs with the API mocked only |
| FR-ASST-03 | ✅ | `assistant.test` role refusal makes no API call |
| FR-ASST-04 | ✅ | `assistant.test` unknown input and error cards; `cards.test` wording |
| FR-ASST-05 | 🟡 | `ConfirmButton` unit-tested (`confirm.test`); its use on each mutating card is by inspection |
| FR-ASST-06 | ✅ | `store.test` cap of 40, in-flight excluded, wiped at sign-out |
| FR-ASST-07 | 🟡 | Implemented; no test |
| FR-ASST-08 | 🟡 | `role="log"` and `aria-live` present by inspection; not tested with a screen reader |
| FR-ASST-09 | 🟡 | Links present on evidence, custody and upload cards; only rendering is unit-tested |

### 3.4 Evidence

| ID | Status | Evidence or gap |
|---|:-:|---|
| FR-EVID-01 | 🟡 | Regex validation in page; no test |
| FR-EVID-02 | 🟡 | Implemented; no test |
| FR-EVID-03 | 🟡 | Header sending tested (`api.test`); 8-character minimum by inspection |
| FR-EVID-04 | 🟡 | SHA-256 primitive tested against a known digest; page flow not exercised |
| FR-EVID-05 | 🟡 | Implemented (no preview on mismatch); not exercised |
| FR-EVID-06 | 🟡 | Implemented; not exercised |
| FR-EVID-07 | 🟡 | Cleanup effect in `AccessPanel`; not exercised |
| FR-EVID-08 | 🟡 | Implemented; card variant tested, tab not |
| FR-EVID-09 | 🟡 | Ed25519 verify and canonical JSON tested against the Python service vector (valid and tampered); `cards.test` shows "unchecked" wording; tab wiring not exercised |
| FR-EVID-10 | 🟡 | Implemented; no test |
| FR-EVID-11 | 🟡 | Implemented with `ConfirmButton`; no page test |
| FR-EVID-12 | 🟡 | Request shape tested (`store.test`); form not exercised |
| FR-EVID-13 | ✅ | `store.test` dedupe, bound of 12, clear |
| FR-EVID-14 | 🟡 | Tab held in the URL search parameter; not tested |

### 3.5 Uploads and quarantine

| ID | Status | Evidence or gap |
|---|:-:|---|
| FR-UPL-01 | 🟡 | Implemented; no page test |
| FR-UPL-02 | 🟡 | Implemented; no page test |
| FR-UPL-03 | 🟡 | `refetchInterval` conditional on state; not tested |
| FR-UPL-04 | 🟡 | Implemented; labels rules vs rules + AI; not tested |
| FR-UPL-05 | 🟡 | Label present; advisory drives no mutation (inspection) |
| FR-UPL-06 | 🟡 | Request shape tested (`store.test`); form and confirm not exercised |
| FR-UPL-07 | 🟡 | Shared `DataTable`; not tested |

### 3.6 Alerts

| ID | Status | Evidence or gap |
|---|:-:|---|
| FR-ALRT-01 | 🟡 | Implemented; severity sort function by inspection |
| FR-ALRT-02 | 🟡 | Implemented; no test |
| FR-ALRT-03 | 🟡 | Implemented with `ConfirmButton`; no page test |
| FR-ALRT-04 | 🟡 | `refetchInterval` 30 s by configuration |

### 3.7 Audit log

| ID | Status | Evidence or gap |
|---|:-:|---|
| FR-AUD-01 | 🟡 | Implemented; no page test |
| FR-AUD-02 | 🟡 | Footnote implemented |
| FR-AUD-03 | 🟡 | Implemented; verify request path tested only via the assistant |
| FR-AUD-04 | 🟡 | Implemented |

### 3.8 Devices

| ID | Status | Evidence or gap |
|---|:-:|---|
| FR-DEV-01 | 🟡 | Client-side validation patterns in page; request shape tested |
| FR-DEV-02 | 🟡 | Implemented with `ConfirmButton`; server refusal rendered by `ErrorState` |
| FR-DEV-03 | 🟡 | Assistant `gaps` tested; page form not |

### 3.9 Settings

| ID | Status | Evidence or gap |
|---|:-:|---|
| FR-SET-01 | 🟡 | Theme application and persistence logic tested (`store.test`) |
| FR-SET-02 | 🟡 | Implemented; no test |

### 3.10 Non-functional

| ID | Status | Evidence or gap |
|---|:-:|---|
| NFR-SEC-01 | ✅ | Only `lib/api.ts` calls `fetch` (grep); built bundle contains no third-party URLs (grep) |
| NFR-SEC-02 | 🟡 | Demonstrated with real nginx 1.24 rendering the same template and include: six headers present on SPA, asset, fallback and proxied routes. Container image build not run |
| NFR-SEC-03 | ✅ | ESLint `no-restricted-syntax` rule; lint clean |
| NFR-SEC-04 | 🟡 | Image uses `nginx-unprivileged`; compose drops all capabilities. Not built or run here |
| NFR-SEC-05 | 🟡 | By inspection: no persistence of Blobs |
| NFR-SEC-06 | 🟡 | `npm audit` reported 0 vulnerabilities locally; `npm ci --ignore-scripts` and audit step wired in CI, which has not run |
| NFR-SEC-07 | 🟡 | Design: API enforces (existing 45 back-end tests); UI gating is display only |
| NFR-REL-01 | ✅ | `api.test` timeout produces a `timeout` error |
| NFR-REL-02 | 🟡 | `ApiError.retryable` tested; the retry policy in `main.tsx` is not |
| NFR-REL-03 | 🟡 | `ErrorBoundary` implemented; not asserted |
| NFR-REL-04 | 🟡 | Banner and pill implemented; not asserted |
| NFR-REL-05 | ✅ | `api.test` keeps request ID; `assistant.test` error card carries it |
| NFR-REL-06 | ✅ | `api.test` 503 mapped to audit failure |
| NFR-REL-07 | 🟡 | Assistant tolerates missing metrics (tested); dashboard by inspection |
| NFR-UX-01 | 🟠 | Radix primitives, landmarks, skip link, labels, `aria-sort`; no automated or manual WCAG audit performed |
| NFR-UX-02 | 🟡 | Token contrast computed by script: dark text tokens 6.2 or higher, light text tokens 5.05 or higher on card and muted backgrounds; not measured in rendered pages. Words accompany colour in badges |
| NFR-UX-03 | 🟡 | `MotionConfig reducedMotion="user"` and CSS media query; not tested |
| NFR-UX-04 | 🟡 | Responsive classes; never viewed at 360 px |
| NFR-UX-05 | 🟡 | `ConfirmButton` tested; consistent use by inspection |
| NFR-PERF-01 | ✅ | Measured 224.7 kB gzip JS (< 250); build warning limit set to 800 kB |
| NFR-PERF-02 | ✅ | Demonstrated: `immutable` on assets, `no-store` on index |
| NFR-PERF-03 | 🟡 | `proxy_buffering off` and `proxy_request_buffering off` in config; large-stream behaviour not tested |
| NFR-DEV-01 | 🟡 | `web` and `stack` jobs added to `ci-ok` needs; `actionlint` clean; not run on GitHub |
| NFR-DEV-02 | ✅ | Vitest thresholds (80/75/80/70) enforced; run result 82.9 % lines, 84.4 % statements |
| NFR-DEV-03 | ✅ | `lib.test` canonical JSON and signature against `tests/vectors/manifest_vector.json` |
| NFR-DEV-04 | 🟡 | `stack` job written; not run (no Docker here) |
| NFR-DEV-05 | 🟡 | `release.yml` builds and signs the web image; not run |
| NFR-DEV-06 | 🟠 | Ubuntu 24.04 native path executed here; WSL and Windows paths not executed |
| NFR-DEV-07 | ✅ | No Dependabot or bot configuration exists in the repository |

### 3.11 Linux / WSL workflow

| ID | Status | Evidence or gap |
|---|:-:|---|
| FR-LNX-01 | 🟠 | Report mode executed; `--install` (apt, NodeSource) not executed |
| FR-LNX-02 | 🟠 | `check.sh --native` executed and passed; `--docker` mode not executed |
| FR-LNX-03 | ✅ | `dev.sh` started API and Vite; proxy and token round trip verified; stop-on-exit confirmed |
| FR-LNX-04 | ✅ | `dev-token.sh` token accepted by the API; `set-owner.sh` run on a copy |
| FR-LNX-05 | 🟡 | Logic written; not run under WSL |
| FR-LNX-06 | 🟡 | Only change is an added web step in `check.cmd`; not run on Windows |
| FR-LNX-07 | ✅ | `test_simulate_seed` plus a live run against a real server |
| FR-LNX-08 | ✅ | `WALKTHROUGH.md` Parts 4b and 10; `README.md` updated |

## 4. Deviations from the plan

1. **No list or search screens for evidence and uploads.** The API has no listing endpoints (SRS constraint C4). Lookup-by-ID plus recent items replaces them. The Deep Dive names the endpoint that would fix it.
2. **Sign-in is token paste**, not OIDC. Right for a reference build; documented as the production gap.
3. **Signing an audit checkpoint sits on the Dashboard**, not the Audit page, because the `admin` role holds `audit:checkpoint` but not `audit:read`.
4. **TanStack Table 8, not the newest major**, and **code-based TanStack Router routes**, chosen for API stability. Vite 8, React 19, Tailwind 4, TypeScript 5.9 and ESLint 9 are current.
5. **Assistant is a rules router, not an LLM.** Deliberate (FR-ASST-02); the service's optional AI summary is displayed and labelled where it exists.
6. **Wireframes are ASCII/Mermaid drawings** in Markdown, not editable Figma artboards, and were not visually checked against a running build.
7. **Browser evidence ceiling of 256 MiB** (FR-EVID-06), by design.
8. **A new CLI command (`custody-admin seed`) and its test** were added to make the console demonstrable. It is development-only and outside the API.
9. **Light-theme status colours were darkened** after a contrast calculation showed the first palette failed 4.5:1; the accent used as text now has its own token.

## 5. Items not executed in this environment

* `docker build` of either image, `docker compose up`, and therefore the `stack` job's probes. The Dockerfile's `COPY` of the header include and the envsubst template path are unproven inside the image.
* Any GitHub Actions run: `ci.yml` (new `web`, `stack`), `security.yml` (new web audit), `release.yml` (web image build and cosign). `actionlint` validated syntax only.
* A real browser: rendering, layout at 360 px, focus order, motion, clipboard, downloads, object-URL previews, video playback.
* Ed25519 verification **in browsers**. Node 22's WebCrypto verified the vector; Safari, Firefox and Chromium versions differ in support.
* Accessibility: no axe scan, no screen-reader pass, no keyboard-only walkthrough.
* Windows 11 execution of `check.cmd` and the unchanged Windows steps; WSL execution of anything; `setup-linux.sh --install`; `check.sh --docker`.
* Python 3.13 (CI matrix) and the existing S3 adapter against a real bucket.
* Load, soak and large-file behaviour through the proxy.
* Final re-run of the complete `check.sh --native` after the last edits (contrast tokens, checkpoint move, ConfirmButton test) is recorded in the delivery message, not here.

## 6. Residual risks and recommended next steps

| # | Risk | Suggested action |
|---|---|---|
| 1 | Page components lack tests; regressions could ship green | Add Playwright journeys for: sign-in, evidence access (verified and mismatch), quarantine review, alert acknowledge |
| 2 | Accessibility claims are design intent only | Add `@axe-core/playwright` to CI; manual NVDA/VoiceOver pass; keyboard-only walkthrough |
| 3 | Docker and compose path unproven | Let the first PR run CI; fix any Dockerfile or compose issue it reveals before merging |
| 4 | Token paste and `sessionStorage` expose the token to any script that runs in the page | CSP mitigates; move to OIDC with short-lived, sender-constrained tokens |
| 5 | Client mirror of the permission table can drift | Add `GET /v1/me` returning role and permissions; delete `lib/auth.ts` table |
| 6 | Browsers without Ed25519 cannot verify reports | Ship a small audited WebAssembly or JS fallback, or state the browser baseline |
| 7 | `/metrics` is proxied to browsers | Restrict to an internal network or authenticate it; move KPIs to an authenticated summary endpoint |
| 8 | Single 725 kB bundle | Route-level code splitting when the app grows |
| 9 | Wireframes may diverge from the running UI | Capture real screenshots in Playwright and add them beside the drawings |
