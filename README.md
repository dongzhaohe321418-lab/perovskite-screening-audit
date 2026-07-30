# perovskite-screening-audit

This repository stores immutable raw audit artifacts for `perovskite-screening`.

The only long-lived branch is `audit`. Codex-as-auditor may add files only under:

```text
projects/perovskite-screening/cycles/<cycle_id>/
```

Each finalized cycle requires:

```text
audit_report.md
audit_result.json
codex_run_metadata.json
report_manifest.json
```

Optional copied inputs are `audit_request.json` and `evidence_manifest.json`.

The Controller validates every fixed Audit Repo commit before recording a cycle as `FINAL`. Audit commits must not contain or modify policy, active blockers, event logs, Claude dispositions, PI approvals, historical cycles, production state, or unrelated project paths.

Controller state is deliberately stored outside this repository.
