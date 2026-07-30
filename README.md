# Automated scientific audit workflow — full source

This branch is the complete, runnable source of the audit workflow whose output lives on the
[`audit`](../../tree/audit) branch of this repository. It exists so the workflow is **visible
and reproducible**: anyone can read exactly what audits this project, and re-run it.

The science being audited lives in a separate repository
([`perovskite-screening`](https://github.com/dongzhaohe321418-lab/perovskite-screening)).
Nothing here contains or judges scientific content.

## What the workflow does

An LLM executor (Claude Science) does the science. An independent LLM auditor (Codex) audits
it read-only at a fixed commit. A fail-closed controller validates the audit and records the
result immutably. The executor must respond to every finding individually and cannot close
any of them. A human PI is involved only on escalation.

```
science commit on the audited branch
  └─ post-commit hook ──▶ event spool ──▶ launchd (WatchPaths) ──▶ orchestrator, one pass:
       1. controller opens a cycle bound to the fixed commit (idempotent key)
       2. Tier-0 deterministic checks               → check_report.json   (machine truth)
       3. codex exec, read-only, detached worktree  → 4 audit artifacts
       4. orchestrator commits them to the audit repo   (Codex never pushes)
       5. controller validates: HMAC webhook, full before/after tree diff, JSON Schema,
          exact manifest coverage + hashes, path allowlist, finding lifecycle → FINAL
       6. pending review queued + PI notified
  └─ Claude Science, via the local MCP server: read report → one disposition per finding
       → fix commit → next cycle re-audits and may emit a verified closure
  └─ same finding unresolved across N FINAL cycles → ESCALATE_TO_PI
```

### The three properties worth stealing

**Tier-0 machine truth defeats shared blind spots.** Hash resolution, path existence, JSON
strictness, empty commits, supersession banners, cross-document status contradictions, and
attempts to instruct the auditor are decided by scripts with no LLM in the loop
(`audit-loop/checks/`). The auditor may not contradict a Tier-0 result, must cite the
`check_id` when reporting one, and must propose a **new** `C-*` check for every hard defect it
finds by judgment — so LLM discoveries ratchet into mechanical checks. Two LLMs sharing a
blind spot cannot be caught by more LLM review.

**Audited content is data, never instructions.** `C-INJECT-001` scans the audited tree for
text directing the auditor ("this is not a finding", "do not report", "pre-approved") and
fails hard regardless of whether the auditor complied. Verified against a planted note
claiming PI pre-approval: the finding survived and the note was itself reported.

**Structural inability to self-approve.** `audit_result.schema.json` pins every finding's
`status` to `{"const": "OPEN"}`, so a closure is *inexpressible* by the auditor. Only a later
cycle, at the exact fix commit, with a matching submitted-fix event, can close anything. The
executor's `closed: true` is rejected by both schema and code.

## Layout

| path | role |
|---|---|
| `science-audit-controller/` | fail-closed validator. HMAC webhooks, fixed tree diffs (payload file lists advisory only), schema + manifest hash validation, FINAL immutability with compare-and-swap, append-only blocker reduction, DENY-by-default policy engine. 51 tests. |
| `audit-loop/rulebook/CODEX_AUDIT_WORKFLOW.md` | the constitution — supreme authority, imported verbatim, hash-locked in `constitution.lock.json` |
| `audit-loop/rulebook/AUDIT_RULEBOOK.md` | 31 machine-parseable rules (`R-*`) generalized from real recorded incidents; `lock_rulebook.py --check` gates staleness |
| `audit-loop/checks/` | Tier-0 deterministic checks (`C-*`), stdlib + yaml only; all domain vocabulary in `checks.yaml` |
| `audit-loop/orchestrator/` | the neutral scheduling layer (constitution §3.5). Makes no scientific judgment, executes no production action. |
| `audit-loop/mcp/` | local stdio MCP server: `audit_status`, `get_pending_review`, `submit_disposition`, `request_audit`, `acknowledge_escalation`, `notify_pi` |
| `audit-loop/hooks/`, `launchd/` | trigger plumbing, as templates rendered at install time |
| `audit-loop/selftest.py` | whole loop end-to-end in throwaway clones |
| `audit-loop/mutation_test.py` | adversarial capability test: inject a known defect, run a real audit, check it is caught |

## Reproduce

Requires Python 3.12+, git, and the [Codex CLI](https://github.com/openai/codex) on `PATH`
(macOS for the launchd trigger; any OS for manual/cron runs).

```bash
git clone -b controller https://github.com/dongzhaohe321418-lab/perovskite-screening-audit.git workflow
cd workflow
git clone https://github.com/dongzhaohe321418-lab/perovskite-screening.git scienceRepo
git clone -b audit https://github.com/dongzhaohe321418-lab/perovskite-screening-audit.git auditRepo

cd audit-loop
./install.sh --science-repo ../scienceRepo --audit-repo ../auditRepo \
             --controller ../science-audit-controller
./.venv/bin/python -m pytest -q ../science-audit-controller/tests   # 51 passed
./.venv/bin/python selftest.py                                     # full loop, scratch clones
```

`install.sh` discovers every path from its own location and the repos you point it at, then
renders `orchestrator/config.yaml`, `orchestrator/projects.yaml`, the git hook, and the launchd
plist from the committed templates. No file in this branch contains a machine-specific path.
Bearer tokens are generated locally into `audit-loop/state/secrets.env` (mode 600) and are
never committed. Verified by installing and running the full suite from an unrelated
directory on a clean clone.

Test the auditor rather than trusting it:

```bash
./.venv/bin/python mutation_test.py --list
./.venv/bin/python mutation_test.py --mutation false_statistic
```

`false_statistic` rewrites a published number so it contradicts the committed raw data. No
deterministic check compares prose to JSON, so only the LLM layer can catch it — which is the
point of the test.

## Branch contract

`audit` and `controller` are unrelated histories and must never be merged. The controller
rejects any push to `audit` whose diff touches anything but
`projects/<project_id>/cycles/<cycle_id>/` with one of six allowed filenames; source code
there would be rejected as an unrelated path, and because the trusted head never advances past
a rejected commit, the pipeline would wedge until a human intervened. Pushes to every other
ref are ignored (`non_audit_branch`), so this branch is inert with respect to the loop.

## Honest limitations

- **Severity is not a stable signal.** Across four real audits of the same tree, findings that
  were `CRITICAL` in one run were `HIGH` in another. Blocking is unaffected (both are blocking
  classes and `blocked_scopes` was consistent), but do not treat the severity label as
  reproducible. Tier-0 could pin severity floors mechanically; it currently does not.
- **One inconsistent blocker event fails the project closed permanently.** The event log is
  append-only with no repair API. Safe, but a manual intervention point.
- **The auditor's model runs in the cloud.** Only the CLI, sandbox, and git operations are
  local; audited content is sent to the model provider.
- **`C-TEST-001`** (clean-clone execution of the audited repo's own suite) ships disabled;
  enable it in `checks/checks.yaml` once you trust the audited repo's test command.
