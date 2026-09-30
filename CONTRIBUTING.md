# Contributing

* `make check` must pass. CI mirrors it.
* **Dependencies are updated deliberately, not by bots.** There is no Dependabot/Renovate. A weekly
  `security.yml` run audits `constraints.txt` and npm and reports in the job summary. To update: change
  the pin(s) in `constraints.txt` in one focused PR, run `make check`, done. No automated PRs or branches.
* Pin GitHub Actions to commit SHAs before adopting in a regulated org (tags are used here for readability).
* Never commit real evidence, CJI, or credentials. Use simulated data (`custody-admin demo`).
* AI features must degrade to deterministic behavior; add/extend `evals/cases.jsonl` with every triage change.
