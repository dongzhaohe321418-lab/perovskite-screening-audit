## Audit decision: BLOCK

Decision: BLOCK

Audited commit: `ad8757317e6a1b6aaa31d640e837bc64da2c7717` (detached, clean read-only worktree)

Decision scope: Q2 production CI-NEB barrier extraction and any resulting `publish_claim`.

### Independently verified

- The fixed worktree resolves to the requested commit and has no local status output.
- Tier-0 reports all HARD checks as PASS. The sole SKIP is the SOFT `C-SCOPE-001`; no HARD check is SKIP or ERROR.
- In an isolated clone at the fixed commit, `python3 scripts/20_test_checks.py` exited 0 and emitted all 47 numbered groups.
- The two committed production NEB outputs contain formal convergence plus `JOB DONE` (q=0: 36 iterations; q=+1: 37). This verifies execution-state records only; it does not authorise extraction or establish a barrier claim.
- The current Q2 index and production-status authority consistently state that barriers are unextracted and require an explicit `check_action` ALLOW.

### Atomic claim verification

| Claim ID | Atomic claim | Evidence / independent check | Status |
|---|---|---|---|
| C-001 | Snapshot is the requested commit. | `git rev-parse HEAD`; empty `git status --short`. | VERIFIED |
| C-002 | Both production legs formally converged. | Decompressed raw `q0_neb.out.gz` and `q1_neb.out.gz` contain the corresponding convergence and completion records. | VERIFIED |
| C-003 | Q2 barriers remain unextracted pending explicit ALLOW. | `RESULTS_INDEX.md` and `PRODUCTION_NEB_STATUS.md`. | VERIFIED as stated current status |
| C-004 | The new extractor refuses any extraction lacking an actual ALLOW. | Isolated-copy execution with valid-format unrecorded token `arbitrary` exited 0 and wrote JSON. | BLOCKED / false |
| C-005 | Regression group 47 protects C-004. | Group 47 passed but tests only blacklisted placeholder strings and omitted an arbitrary valid-format token. | BLOCKED / inadequate guard |

### Blocking findings

1. [HIGH] F-025 — unauthenticated gate token permits barrier extraction before `check_action` ALLOW.

   `scripts/27_extract_barriers.py:91-95` validates only token syntax and five literal blacklist values, despite asserting that it accepts a recorded ALLOW consultation ID. In an isolated clone of this exact commit, `python3 scripts/27_extract_barriers.py --gate-token arbitrary --out ../unauthorized.json` exited 0 and created a nonempty extraction record. The existing group-47 regression (`scripts/20_test_checks.py:1365-1380`) tests only `PENDING`, `NONE`, `DENY`, and `PLACEHOLDER`, so it passes while this bypass remains.

   Impact: a barrier value and charge-state comparison can be materialized without the explicit controller `check_action(action="publish_claim")` ALLOW that the canonical Q2 records require. This blocks `publish_claim`; it does not alter the recorded raw-run state.

   Minimum fix: make the extractor verify a durable, committed/controller-authenticated ALLOW record bound to this commit, `publish_claim`, and the invocation; reject any unresolvable or mismatched token before reading outputs or writing JSON. Add a regression fixture for a syntactically valid but unrecorded token and require nonzero exit and no output file.

### Non-blocking caveats

- Tier-0 `C-SCOPE-001` is SKIP because the declared audit scope is prose rather than machine-readable path patterns. It is SOFT and not a basis for this BLOCK.
- This audit did not extract or quote any Q2 activation energy; the unauthorized probe record existed only in the isolated copy used to demonstrate the gate defect.

### Independent recomputations

- Execution completion: decompressed each committed production output and independently located `neb: convergence achieved` and `JOB DONE` records.
- Guard behaviour: ran the full suite in an isolated clone (exit 0), then exercised the extractor with an unrecorded but valid-format token. It wrote a record containing both leg iteration counts and raw-output custody metadata, proving the token check is not tied to an ALLOW record.

### Recommendation to Claude Science

- Do not invoke or publish the Q2 barrier extraction until F-025 is repaired and independently re-audited. Implement provenance-bound ALLOW verification and a positive/negative fixture pair; then submit the new fixed commit for a clean-clone audit.

### Forbidden until closure

- `publish_claim` for any extracted Q2 barrier, direction, or charge-state ordering.

### Required next report

- Fixed commit SHA; the committed or controller-verifiable ALLOW-record format and binding fields; clean-clone output for an authentic ALLOW case and an arbitrary valid-format non-ALLOW case; proof the latter writes no record; and the updated regression fixture output.

### Execution declaration

- Codex repository changes: NONE (science worktree unchanged).
- Codex remote/HPC/GPU/instrument actions: NONE.
