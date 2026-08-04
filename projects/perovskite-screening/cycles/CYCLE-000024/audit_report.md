## Audit decision: BLOCK

Decision: BLOCK

Audited commit: `485106fa144ccd74fff77144634b65e15c38eb71`

Decision scope: Q2 barrier-extraction/publication claim and any other claim relying on the repository regression-suite receipt. This decision applies only to this fixed snapshot.

### Independently verified

- The fixed detached snapshot resolves to the requested commit and the policy-bundle hashes match the locally read constitution and rulebook.
- Tier-0 reports PASS for every HARD check. Its sole SKIP is `C-SCOPE-001`, a SOFT scope-format check.
- The submitted F-024 repair commit `7a4f3b0e2fcd3d02ac2d3712fd53cad6715fff88` is not an ancestor of this snapshot.
- Q2 raw NEB outputs each contain `neb: convergence achieved` followed by `JOB DONE` (36 q=0 and 37 q=+1 iterations). The production-status record does not quote barriers, so no barrier ordering was audited as established.
- `derive_q3.py` completed successfully from committed Q3 records and reproduced its stated state-ID and alignment values. The Q3 authority and index status were sampled for consistency.
- Independently recomputed the control XRD DOC range from the committed `.txt`/`.mdi` pair: 49.030543–65.218597%, consistent after rounding with `summary_metrics.csv`; the canonical index carries the current passivator-screen row.
- Recomputed the Q1 reported means and sample standard deviations from `corpus108_stats.json`: GA n=11, mean +6.8 meV, sd 47.4 meV; Sr n=12, mean -4.3 meV, sd 59.6 meV.

### Blocking findings

1. [HIGH] F-024 — Regression guard receipts state failure propositions after passing.
   
   The fixed commit retains `expect(cond, msg)` with one message on both branches. In an isolated clone, group [41] emits `ok ... is not marked historical` even though the cited record is expressly historical; group [44] likewise emits `ok ... current entry missing on disk` for present entries. The suite exits 0, but these successful receipts assert the inverse of the predicate that passed. This prevents a green guard receipt from serving as truthful evidence for publication.
   
   Minimum fix: incorporate the submitted `ok_msg` success branch (or equivalent) and fixture/AST regression into a descendant commit, then clean-clone rerun it. Acceptance requires success receipts to state the satisfied condition and rejection receipts to state the violation.

### Non-blocking caveats

- `C-SCOPE-001` is SKIP because the audit scope is prose rather than machine-readable path patterns. It is SOFT and does not affect this BLOCK decision.

### Independent recomputations

- Q1 summary: `corpus108_stats.json` values → Python `statistics.mean`/`statistics.stdev` → figures above.
- Q3: committed `q3_raw` inputs → `derive_q3.py` → successful assertions for quoted authority values.
- XRD: committed control raw/sidecar → `xrd_protocol_kernel.analyse_single` → DOC range above.
- Q2 completion state: compressed q0/q1 raw logs → decompression and completion-marker search → 36/37 iteration completion records.

### Recommendation to Claude Science

- Do not use this snapshot's regression-suite success transcript to support a publication claim. Apply the already submitted F-024 repair in a new commit and request a fresh fixed-commit audit.

### Forbidden until closure

- `publish_claim` actions relying on the regression-suite receipt from this snapshot.

### Required next report

- New fixed commit SHA; ancestry proof for the F-024 repair; clean-clone test command and exit code; accepted and rejected fixture receipts showing distinct truthful messages.

### Execution declaration

- Codex repository changes: NONE (science worktree unchanged).
- Codex remote/HPC/GPU/instrument actions: NONE.
