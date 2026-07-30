# science-audit-controller

`science-audit-controller` is the fail-closed workflow controller between the read-only Science Repo and the audit-artifact-only Audit Repo. It validates and records workflow facts; it does not make scientific judgments or execute production actions.

Version 1.0 runs one configured project per controller instance. This keeps repository identity and trusted audit history unambiguous.

## Security Properties

- Every GitHub webhook requires a valid SHA-256 signature. A missing secret disables the endpoint with `503`.
- Repository decisions use a complete fixed `before`/`after` tree comparison from Git or the GitHub API. Payload file lists are advisory only.
- Delivery claims are atomic, concurrent duplicates are suppressed, and failed deliveries remain retryable.
- A cycle cannot become `FINAL` without all four required artifacts, strict JSON Schema validation, exact manifest coverage, and matching hashes.
- A `FINAL` audit commit, result, report ID, and report hash are immutable. Re-delivery of the same commit is idempotent.
- Claude submissions require authentication, exact report-hash confirmation, one unique disposition per finding, and an existing new fix commit.
- A submitted fix does not close a finding. Only a later audit cycle at that exact commit can emit a verified closure.
- High-risk actions default to `DENY`. `ALLOW` requires an exact permissive FINAL audit, matching manifest, no applicable blocker, and unexpired policy, budget, and PI approvals.
- Only the PI can quarantine a blocker event. Quarantine is append-only, never removes an event from the event log, and removes an event from the blocker fold without declaring any finding resolved.

## Repository Contract

The configured Audit Repo has one long-lived branch, `audit`. A valid audit commit changes files in exactly one directory:

```text
projects/perovskite-screening/cycles/<cycle_id>/
```

Required artifacts:

```text
audit_report.md
audit_result.json
codex_run_metadata.json
report_manifest.json
```

Optional copied inputs are `audit_request.json` and `evidence_manifest.json`. When present, they must also be included in `report_manifest.json`. Codex cannot change policy, blocker state, the event log, dispositions, PI approvals, historical cycles, or unrelated paths.

`codex_run_metadata.json` must bind the run to `cycle_id` and the full `audited_commit`. A later audit closes a submitted fix through `audit_result.json`:

```json
{
  "verified_closed_findings": [
    {
      "finding_id": "F-001",
      "verification_summary": "The regression test passes at the submitted fix commit."
    }
  ]
}
```

## Install and Test

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[test]"
python -m pytest -q
```

GitHub Actions runs the same suite from `.github/workflows/ci.yml`.

## Run Locally

```bash
cp .env.example .env
set -a
source .env
set +a
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

For local-clone mode, set `SCIENCE_REPO_PATH` and `AUDIT_REPO_PATH`. The controller reads files and diffs at webhook commit SHAs; both clones must already contain those objects.

## Run Against GitHub

Deploy the Docker image as a persistent HTTPS service. A GitHub Actions job alone cannot receive webhooks continuously.

1. Set all required values from `.env.example` in the deployment secret store.
2. Give `GITHUB_TOKEN` read access to both configured repositories.
3. Set `audit_initial_commit` to the trusted current Audit Repo commit. The included perovskite configuration pins the initialized local baseline.
4. Run exactly one controller replica and persist `/app/data` on its local filesystem.
5. Configure both repositories to send `push` events to `https://<controller>/webhooks/github`.
6. Use the same `GITHUB_WEBHOOK_SECRET` in GitHub and the deployment.
7. Protect the Audit Repo `audit` branch so only the Codex identity and repository administrators can push.

The GitHub API implementation compares complete recursive trees and fails if GitHub reports a truncated tree. It never uses "latest main."

## API Authentication

All non-webhook control endpoints use distinct bearer tokens:

```text
POST /actions/check           ACTION_API_TOKEN
POST /claude/dispositions     CLAUDE_API_TOKEN
POST /authorizations          PI_APPROVAL_TOKEN
POST /admin/quarantine-event  PI_APPROVAL_TOKEN
GET  /cycles                  CONTROLLER_READ_TOKEN
GET  /events                  CONTROLLER_READ_TOKEN
```

Example high-risk authorization:

```bash
curl -X POST https://<controller>/authorizations \
  -H "Authorization: Bearer $PI_APPROVAL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "authorization_id": "AUTH-000001",
    "project_id": "perovskite-screening",
    "actor": "claude_science",
    "action": "submit_production_job",
    "science_commit": "FULL_40_CHARACTER_COMMIT_SHA",
    "manifest_sha256": "FULL_64_CHARACTER_SHA256",
    "policy_approved": true,
    "budget_approved": true,
    "pi_approved": true,
    "approved_by": "principal-investigator",
    "expires_at": "2026-08-01T00:00:00+00:00"
  }'
```

Authorizations are append-only, expire automatically, and are scoped to an exact actor, action, Science Commit, and manifest hash. The controller only returns a decision; it does not submit a production job.

## Repairing a Fail-Closed Blocker Fold

Blocker state is derived by folding the entire append-only event log. Any inconsistency — a duplicate open, a disposition without an open finding, a closure without a matching re-audit, an unknown event type — sets `fail_closed`. While `fail_closed` is set, every action check returns `DENY` with `BLOCKER_STATE_INCONSISTENT` and no audit can finalize. One bad event would otherwise halt the project permanently.

The canonical identity of an event is the SHA-256 of its canonical JSON:

```python
hashlib.sha256(
    json.dumps(event.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()
```

Every fold error names that hash, so a `DENY` leads directly to the event to quarantine:

```text
close without open finding for F-404 (event_sha256=<64 hex characters>)
```

`GET /events?project_id=perovskite-screening` lists every event with its canonical hash and append-order index, plus the project's quarantine records. Events carrying no `project_id` are included in a project-scoped read, because those are exactly the events that fail that project's fold.

Only the PI can quarantine an event:

```bash
curl -X POST https://<controller>/admin/quarantine-event \
  -H "Authorization: Bearer $PI_APPROVAL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "perovskite-screening",
    "event_sha256": "FULL_64_CHARACTER_SHA256",
    "reason": "Replayed closure event for a finding that was never opened.",
    "approved_by": "principal-investigator"
  }'
```

Quarantine is deliberately narrow:

- The endpoint requires `PI_APPROVAL_TOKEN`. A missing token is `401` and an unconfigured token disables the endpoint with `503`.
- Records are append-only in their own state key alongside `reason` and `approved_by`. Nothing is ever removed from the event log, and re-quarantining the same hash is idempotent.
- A quarantined event is skipped by the fold. It contributes nothing and it cannot set `fail_closed`. It does not close, resolve, or verify anything: quarantining a `FINDING_OPENED` drops the blocker from the active set and emits no closure event, and the quarantine record is the audit trail for why.
- Quarantine cannot revive a `FINAL` cycle's immutability guarantees or change any recorded cycle field. Finding IDs stay unreusable, so a quarantined finding ID cannot be re-reported by a later audit.
- A hash that matches no event is recorded and has no effect, which lets the PI quarantine ahead of a replay.

## Current Adapters

`codex_adapter.py` and `claude_adapter.py` generate and persist versioned task prompts. They intentionally remain adapter boundaries for real Codex and Claude task APIs. Audit validation, policy enforcement, state transitions, authentication, and GitHub commit reads are implemented now.
