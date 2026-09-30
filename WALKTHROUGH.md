# Evidence Custody: Beginner Walkthrough (Windows 11)

Goal: get this project running on your PC, understand it well enough to change it
with confidence, publish it to your own GitHub, and protect `main` so **nothing
changes without you reading and merging it**.

You do **not** need to install Python or Node. Docker runs everything (the API,
the tests, the TypeScript SDK checks) inside Linux containers, which is also what
the project was built and tested on.

There is no bot that opens branches or pull requests (no Dependabot), and nothing
merges by itself. Four workflows exist; Part 8 explains exactly what each one does.

Use **Command Prompt** (press the Windows key, type `cmd`, press Enter) unless a
step says otherwise.

---

## Part 0: What you are looking at (2-minute version)

A body camera records video. Before that video can be used as evidence, someone
must be able to prove **it is exactly what the camera recorded and nobody touched
it**. This project is the upload path that proves it:

```
camera signs a manifest --> uploads in small verified chunks --> server re-hashes the whole file
    --> match?  yes: stored write-once + signed receipt   no: QUARANTINE + alert, never accepted
    --> every step written to a tamper-evident audit log
```

Words you will see everywhere:

| Word | Plain meaning |
|---|---|
| **SHA-256 hash** | A fingerprint of a file. Change one bit and the fingerprint changes completely. |
| **Chunk** | A small slice of the video, uploaded and checked one at a time so a dropped connection just resumes. |
| **Manifest** | The camera's signed list of "here is who I am, and here is the fingerprint of every chunk and of the whole file". |
| **Idempotent** | Sending the same request twice has the same effect as once (no duplicate evidence). |
| **Quarantine** | Where a suspicious upload is kept, untouched, and never shown as trustworthy. |
| **WORM** | Write once, read many. Originals can never be overwritten or deleted. |
| **Audit log** | A diary where each entry contains the fingerprint of the previous one, so editing history is detectable. |

Folder map:

| Folder | What is inside |
|---|---|
| `src/custody/` | The whole service. Start with `service.py` (the workflow) and `app.py` (the web API). |
| `tests/` | 45 tests. They double as documentation of every guarantee. |
| `sdk-ts/` | TypeScript client a camera or gateway could use. |
| `evals/` | The "did the AI triage behave?" test set. |
| `docs/` | Architecture diagrams, threat model, compliance mapping, runbook. |
| `deploy/` | Terraform (locked-down S3 bucket) and Kubernetes files. |
| `.github/workflows/` | The automation (Part 8). |

---

## Part 1: Install the prerequisites (one time)

Run these one at a time. Skip anything you already have.

```
winget install --id Git.Git -e
winget install --id GitHub.cli -e
winget install --id Docker.DockerDesktop -e
```

* **Git** stores your code history. **GitHub CLI (`gh`)** lets you talk to GitHub from the prompt.
* **Docker Desktop** runs the app and the checks. It needs a **restart**, and you must **open Docker Desktop once** and wait until it says "Engine running".

**Close and reopen Command Prompt** after installing so the new programs are found.

```
git --version
gh --version
docker --version
```

Also create a free GitHub account at https://github.com if you don't have one.

> Why not run Python directly on Windows? The storage layer relies on Linux file
> behavior (read-only files, hard links, directory syncing) that behaves
> differently on Windows. The Docker route below avoids all of that.

---

## Part 2: Get the project onto your PC

Pick any folder. Example:

```
mkdir C:\projects
cd C:\projects
tar -xf C:\Users\YOU\Downloads\evidence-custody.zip
cd evidence-custody
```

(Change the path to where the ZIP really is. Windows 11 has `tar` built in.)

### Put your GitHub username into the project

A few files (`CODEOWNERS`, the Kubernetes image name) contain a placeholder
organization name. Replace it with your username (example: `sm2774us`):

```
powershell -ExecutionPolicy Bypass -File .\scripts\set-owner.ps1 -Owner YOUR_GITHUB_USERNAME
```

It prints each file it changed. Only whole-word matches are replaced.

---

## Part 3: See it work in 60 seconds (the demo)

Make sure Docker Desktop is running, then build the image once and run the built-in
simulation:

```
copy .env.example .env
docker compose build
docker compose run --rm api custody-admin demo
```

The first build downloads images and takes a few minutes. The demo then plays a
whole story with a fake camera and prints something like:

```
[1] stored ev_...  retries=1 resent=1                <- connection dropped + a bit flipped, both recovered
[2] tampered object refused ... object_hash_mismatch <- wrong whole-file fingerprint: quarantined
[3] open alerts: [('HASH_MISMATCH', 'high')]
[4] custody events=7 fixity_ok=True audit_chain_ok=True
[5] audit verify: True (16 entries)
```

Read that output line by line. Every line maps to a sentence in the design answer
in `docs/DESIGN_ANSWER.md`. If you understand those five lines, you understand the
project.

---

## Part 4: Run the real server and poke at it

**1. Make real secrets.** The `.env` file needs two random keys. Generate them:

```
docker compose run --rm api custody-admin init
```

Copy the two printed lines (`CUSTODY_SIGNING_KEY=...` and `CUSTODY_TOKEN_SECRET=...`)
into `.env`, replacing the two empty lines with those names. Never commit `.env`
(the project's `.gitignore` already blocks it).

**2. Start the server:**

```
docker compose up --build
```

| What | Address |
|---|---|
| Interactive API docs (Swagger) | http://localhost:8080/docs |
| Health | http://localhost:8080/healthz |
| Is the audit log intact? (503 if not) | http://localhost:8080/readyz |
| Metrics (Prometheus format) | http://localhost:8080/metrics |
| The service's public signing key | http://localhost:8080/v1/keys |

**3. Make yourself a login token.** In a second Command Prompt window, in the same folder:

```
docker compose run --rm api custody-admin issue-token --sub my-auditor --role auditor --agency agency-1
```

Copy the long text it prints. In Swagger open `POST /v1/audit/verify` → **Try it out**,
type `Bearer ` (with the space) followed by your token into the `authorization`
box, and **Execute**. You should see `"ok": true`.

Now try something you are *not* allowed to do: open `GET /v1/evidence/{eid}/content`
with the same auditor token. You get `403`. That refusal is a feature: auditors can read
history but never the video bytes. Look at `GET /v1/audit` afterwards: your refused attempt
is recorded too.

Roles to try with `--role`: `device`, `reader`, `custodian`, `legal`, `auditor`, `admin`.
Each has different permissions (`src/custody/auth.py`, the `PERMISSIONS` table).

Stop with `Ctrl+C`, then clean up (this also deletes the stored data):

```
docker compose down -v
```

---

## Part 5: Run every check (what CI runs, on your PC)

```
scripts\check.cmd
```

It runs, inside containers: formatting and lint (ruff), type checking (mypy), the 45
tests with a coverage gate, the AI-triage evals (no AI needed), the demo, and the
TypeScript SDK type check and tests. It ends with `All checks passed.`

> **Honest heads-up:** this project was built and verified on Python 3.12 / Linux.
> CI and `check.cmd` use Python 3.13. Tooling versions also drift over time (a newer
> `ruff` can add a rule that flags something). If a check fails on the very first
> run, read the message; it is usually a one-line fix. Fix it before Part 7.

---

## Part 6: Publish to GitHub (one time)

**1. Turn the folder into a git repo** (the `-M main` matters: it names the branch `main`):

```
git init
git branch -M main
git add -A
git commit -m "initial commit"
```

If git says it doesn't know who you are, run these once and commit again:

```
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

**2. Log in to GitHub** (opens your browser, one time only):

```
gh auth login
```

**3. Create the repository and upload:**

```
gh repo create evidence-custody --public --source=. --remote=origin --push
```

Use `--private` if you prefer, with two caveats: the branch-protection ruleset in
Part 7 and CodeQL scanning need a public repo or a paid plan.

**4. Keep branch clutter away automatically.** Merged branches get deleted, and only
squash-merging is allowed, so history stays one tidy commit per change:

```
gh repo edit --delete-branch-on-merge --enable-squash-merge --enable-merge-commit=false --enable-rebase-merge=false
```

**5. Turn on GitHub's security *alerts* only** (no automatic PRs): repo page →
**Settings** → **Code security** → enable **Dependabot alerts** and **Dependency graph**.
Leave "Dependabot security updates" and "version updates" **off**.

---

## Part 7: Protect `main` (one time, after CI is green)

### 7a. Wait for the first CI run and get it green

Pushing in Part 6 started the `CI` workflow. Watch it:

```
gh run watch
```

Its required checks are **python 3.12**, **python 3.13**, **typescript**, **workflows-lint**
and **container**, summarized by one final check named **ci-ok (required check)**. If something fails:

```
gh run view --log-failed
```

Fix the file, then `git add -A`, `git commit -m "fix: ..."`, `git push`. Repeat until green.
**Do this before 7b**, because once `main` is protected every fix must go through a pull request.

Things most likely to fail on a brand-new repo (none are bugs in your code):

| Symptom | Cause / fix |
|---|---|
| `container` job fails in "Scan image" | Trivy found a fixable vulnerability in the base image. Rebuild later, or read the report and decide. |
| `security` workflow: CodeQL or dependency-review errors | Private repo without the paid feature, or dependency graph not enabled (Part 6 step 5). |
| `workflows-lint` flags a workflow | actionlint found a real nit. It names the file and line. |
| Lint fails only in CI | A newer ruff/mypy than the one you tested with. Fix the flagged line. |

### 7b. Turn protection on

One command, using the file already in the repo (`.github/rulesets/protect-main.json`):

```
gh api -X POST repos/:owner/:repo/rulesets --input .github/rulesets/protect-main.json
```

`:owner` and `:repo` are filled in automatically from the current folder.

What the rule enforces on `main`:

* nobody can push directly (changes must arrive through a pull request),
* nobody can force-push or delete the branch,
* **`ci-ok (required check)` must be green** before the merge button works,
* review conversations must be resolved,
* **no bypass, including you**.

**Prefer clicking?** Repo → **Settings** → **Rules** → **Rulesets** → **New ruleset** → **Import a ruleset** → choose `.github/rulesets/protect-main.json` → **Create**.

> **Why 0 required approvals?** GitHub does not let you approve your own pull request,
> so on a one-person repo "1 approval" would lock you out. Your supervision is the pull
> request itself: you open it, read the diff, wait for green checks, and click merge
> yourself. If a teammate joins, set `required_approving_review_count` to `1` in the ruleset.

---

## Part 8: Everyday workflow

Rule of thumb: **one branch, one pull request, merged by you, at a time.**

```
git switch main
git pull
git switch -c my-change
```

Edit files, run `scripts\check.cmd`, then:

```
git add -A
git commit -m "feat: describe your change"
git push -u origin my-change
gh pr create --fill
```

Wait for the checks (`gh pr checks --watch`), **read the changes** (`gh pr view --web`
shows the diff in your browser), then merge:

```
gh pr merge --squash --delete-branch
git switch main
git pull
```

### What the four workflows do

| Workflow | When it runs | What it does |
|---|---|---|
| `CI` | Automatically on pushes to `main` and on pull requests | Lint, types, tests, evals, demo, TypeScript checks, workflow lint, container build + scan. Never merges or creates anything. |
| `Security` | Pushes to `main`, pull requests, and **every Monday** | CodeQL, dependency audit, secret scan. Failures appear as red checks or a job summary. Opens no PRs. |
| `AI evals` | Manually, weekly, and on pull requests that touch `triage.py` or `evals/` | Scores the optional AI triage. With no API key it skips the AI part and still checks the rules. |
| `Release` | Only when you push a version tag | Runs CI, publishes a signed Docker image to GitHub Packages, attaches an SBOM, creates a GitHub Release. |

Weekly runs only **report**. Nothing they do changes your code.

To update a dependency (instead of a bot): edit the one pinned line in `constraints.txt`,
run `scripts\check.cmd`, and open a normal pull request.

To make a release, once your PR is merged and `main` is green:

```
git switch main
git pull
git tag v1.0.1
git push origin v1.0.1
```

> Docker image names must be lowercase. If your GitHub username has capital letters
> the release job's image push will fail; rename the repo/owner or lowercase the
> `IMAGE` value in `.github/workflows/release.yml`.

**Optional AI switch.** To let the workflow use a real model for triage summaries:
`gh secret set ANTHROPIC_API_KEY`, and in `.env` set `CUSTODY_AI_ENABLED=1` and
`CUSTODY_ANTHROPIC_API_KEY=...`. Everything works identically without it, by design.

---

## Part 9: Become productive (a guided first change)

**Read in this order** (about an hour):

1. `docs/DESIGN_ANSWER.md`: the interview answer mapped to code.
2. `src/custody/models.py`: the manifest and the upload states.
3. `src/custody/service.py`: `create_upload`, `put_chunk`, `complete`, `_quarantine`. This is the heart.
4. `tests/test_ingest.py` then `tests/test_security.py`: each test is one guarantee in plain code.
5. `docs/THREAT_MODEL.md` and `docs/RUNBOOK.md`.

**Your first change: add a "short" retention class (365 days).** Retention classes decide
how long evidence must be kept.

1. `src/custody/config.py`: add `"short": 365,` inside `RETENTION_DAYS`.
2. `src/custody/models.py`: add `"short"` to the `retention_class` `Literal[...]` list.
3. Add this test at the bottom of `tests/test_ingest.py`:

```python
def test_short_retention_class(env):
    cam, rec = env.stored(retention_class="short")
    r = rec["receipt"]
    assert r["retention_until_ms"] - r["stored_at_ms"] == 365 * 86_400_000
```

4. Run `scripts\check.cmd`. If you forget step 2, the test fails with a clear validation
   error, which is a nice way to see the manifest guard doing its job.
5. Branch, commit, `gh pr create --fill`, read the diff, merge (Part 8).

**Good next exercises:** add a new alert rule in `triage.py` plus a case in
`evals/cases.jsonl`; add a permission to a role in `auth.py` and a test proving the old
role still can't do the forbidden thing.

**Golden rules of this codebase** (also in the PR template):

* Nothing may modify or delete an original, or shorten retention.
* Every state change writes an audit row in the same database transaction.
* New endpoints must declare a permission and be agency-scoped.
* AI can add advice, never decide. The workflow must pass with AI turned off.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `'git' is not recognized` | Close and reopen Command Prompt after installing. |
| Docker errors like "cannot connect to the daemon" | Open Docker Desktop and wait for "Engine running". |
| `docker compose up` says `.env` not found | Run `copy .env.example .env` first. |
| Port 8080 already in use | Close the other program, or run `docker compose down -v`. |
| Every API call returns 401 | Token expired (default 15 minutes) or missing `Bearer ` prefix. Issue a new one. |
| `403 forbidden` on something | Your role lacks that permission. That is intended; check the `PERMISSIONS` table. |
| `/readyz` returns 503 | The audit log failed verification. In real life that is a security incident; in a sandbox, `docker compose down -v` resets it. |
| `scripts\check.cmd` cannot find `constraints.txt` | Run it from the repo root, the folder containing `pyproject.toml`. |
| `gh api ... rulesets` says 403 or "upgrade" | Private repos need a paid plan for rulesets. Make the repo public or use classic protection: Settings → Branches → Add rule → require a pull request and the status check `ci-ok (required check)`. |
| Merge button is greyed out | A check is still running or failed. `gh pr checks` shows which. |
| Rule says a check "is expected" but never appears | The name must match exactly: `ci-ok (required check)` (the job name in `.github/workflows/ci.yml`). |
| Pushed straight to `main` and it was rejected | That is the protection working. Create a branch (Part 8). |

---

## Quick reference: whole sequence

```
:: one time
winget install --id Git.Git -e
winget install --id GitHub.cli -e
winget install --id Docker.DockerDesktop -e
cd C:\projects
tar -xf C:\Users\YOU\Downloads\evidence-custody.zip
cd evidence-custody
powershell -ExecutionPolicy Bypass -File .\scripts\set-owner.ps1 -Owner YOUR_GITHUB_USERNAME
copy .env.example .env
docker compose build
docker compose run --rm api custody-admin demo
scripts\check.cmd
git init
git branch -M main
git add -A
git commit -m "initial commit"
gh auth login
gh repo create evidence-custody --public --source=. --remote=origin --push
gh repo edit --delete-branch-on-merge --enable-squash-merge --enable-merge-commit=false --enable-rebase-merge=false
gh run watch
:: when CI is green:
gh api -X POST repos/:owner/:repo/rulesets --input .github/rulesets/protect-main.json

:: every change
git switch -c my-change
git add -A
git commit -m "feat: ..."
git push -u origin my-change
gh pr create --fill
gh pr checks --watch
gh pr view --web
gh pr merge --squash --delete-branch
git switch main
git pull
```
