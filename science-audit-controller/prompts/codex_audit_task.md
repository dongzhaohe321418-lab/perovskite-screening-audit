# Codex Audit Task Template

Audit the supplied Science Commit and produce the expected artifacts:

- `audit_report.md`
- `audit_result.json`
- `codex_run_metadata.json`
- `report_manifest.json`

Your decision must be one of `PASS`, `PASS_WITH_CAVEATS`, `BLOCK`, or `NOT_VERIFIABLE`. If the decision is `BLOCK`, each blocking finding must include machine-readable `blocked_scopes`.

For a prior finding listed for re-audit, add it to `verified_closed_findings` only when you independently verified the submitted fix at this cycle's fixed Science Commit. Include `finding_id` and a non-empty `verification_summary`. Otherwise leave the finding open.

`codex_run_metadata.json` must include this cycle ID, the fixed audited commit, runner identity, and ISO-8601 start and completion times. `report_manifest.json` must hash every emitted artifact other than itself.

Write only under `projects/<project_id>/cycles/<cycle_id>/` in the Audit Repo branch `audit`.
