## Audit decision: PASS

Decision: PASS

Audited commit: `a75e2f7f2d0d4de113674aeb2a5490e1c79bfcd5` (fixed snapshot only)

Decision scope: closure review of F-005 and F-009, plus independent provenance, current-authority, Q3, and XRD spot checks at the fixed commit.

### Independently verified

- F-005 is closed. Tier-0 `C-LINK-001` is PASS: all 387 repository-path-shaped references in 73 scanned files resolve. This is the authoritative machine result for the former unresolved-link finding.
- F-009 is closed. In an isolated detached clone of the fixed commit, `python3 scripts/20_test_checks.py` exited 0 and executed the numbered regression suite through group 41.
- The repository remains at the requested detached commit with a clean status. Tier-0 reports 11 PASS, no FAIL, no HARD SKIP/ERROR, and one non-blocking SOFT scope SKIP.

### Blocking findings

None.

### Non-blocking caveats

None introduced by this audit. Existing repository wording continues to reserve the production q=0/q=+1 CI-NEB launch for an explicit PI go; this is not a Codex authorization.

### Independent recomputations

- Q3 authority chain: committed `derive_q3.py` rebuilt the 160-to-159 mapping (159 shared atoms), reproduced cosine 0.9757, effective-atom counts 35.6/38.3, and aligned values +75.8/+52.1 meV from the committed raw outputs; exit 0.
- XRD DOC: `xrd_protocol_kernel.analyse_single` on the committed control `.txt/.mdi` returned `49.030543–65.218597%`, consistent with `summary_metrics.csv` and the current 49–65% README wording.

### Recommendation to Claude Science

- Record F-005 and F-009 as independently verified closed. No repository modification or production action follows from this PASS opinion.

### Forbidden until closure

- No additional action is forbidden by findings in this cycle. Any production submission remains subject to the repository's stated PI authorization and protocol gates.

### Required next report

- For any new commit or production request: fixed commit SHA, exact requested action, current gate/PI status, input manifest hashes, raw evidence paths, executed commands with exit codes, and dispositions for any new findings.

### Execution declaration

- Codex repository changes: NONE to the audited Science worktree.
- Codex remote/HPC/GPU/instrument actions: NONE.
- Audit artifacts were written only under this cycle's `out/` directory.
