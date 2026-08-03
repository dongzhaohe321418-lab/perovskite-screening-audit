## Audit decision: BLOCK

Decision: BLOCK

Audited commit: a01e54cff8137b9622ab045c4d5f2cf789beb268

Decision scope: `publish_claim`, including the requested Q2 barrier-extraction claim and any current Q3 or XRD claim.

This decision applies only to the fixed detached snapshot above. The worktree was clean and its `HEAD` matched the requested commit.

### Independently verified

- The policy-bundle rulebook digest matches the raw `AUDIT_RULEBOOK.md` digest; the fixed evidence-manifest raw-byte SHA-256 equals the request value `c9b2f142…bb7447`.
- Q3 raw derivation completed successfully from committed inputs: custody hashes, 160→159 mapping, cosine 0.9757, alignments +75.8/+52.1 meV, and bounded POL quantities reproduced.
- Q1 raw-pair recomputation from the 108 rows plus `admission_108.json` reproduced GA (n=11, +6.8 meV, CI [−25.0, +38.6]) and Sr (n=12, −4.3 meV, CI [−42.2, +33.6]).
- Both production NEB outputs contain formal convergence and `JOB DONE` (q=0: 36 iterations; q=+1: 37). No barrier value was audited as extracted.
- All 76 tracked JSON files parsed; all tracked gzip members passed integrity testing. The XRD control raw-data recomputation reproduced the reported DOC range (49.030543–65.218597%).
- Tier-0 is respected as machine truth: 11 checks PASS; the one SKIP is the non-blocking soft scope check.

### Blocking findings

1. [HIGH] F-019 — Q3 citability remains contradictory in its index-named authorities and Q0 gate. `RESULTS_INDEX.md` declares Q3 CITABLE/closed, but the three declared Q3 authorities still say citability awaits the next independent audit and the condition-3 PASS row says independent re-verification is pending/owed. These assertions lack a historical/superseded marker. The submitted repair `1cca3f6…` is not an ancestor of this snapshot. Minimum fix: apply and independently verify a single propagated state across index, all named authorities, and gate, with a repo-wide regression.

2. [HIGH] F-022 — The q=+1 production staging manifest asserts `BLOCKED_DO_NOT_SUBMIT` and “not a real staging operation,” while the current production authority states both legs converged and that the same q=+1 input gap is closed. The unmarked manifest leaves contradictory provenance for the claimed production run. Minimum fix: preserve the invalid historical staging record with an explicit supersession banner and add a committed, hash-bound actual staging/run-custody record (or correct the current authority to its evidenced state).

3. [HIGH] F-023 — The repository’s declared canonical index omits the live six-film XRD passivator conclusion. `RESULTS_INDEX.md` points only to the control-only `xrd/README.md`; neither it nor that README names `xrd/PASSIVATOR_SCREEN.md`, which has unmarked current conclusions for P1–P5. Minimum fix: add a canonical XRD question row that names the passivator authority, raw-data/results paths, scope, status, and next action.

### Non-blocking caveats

- Tier-0 `C-SCOPE-001` is SKIP because the audit scope is prose rather than machine-readable path patterns. This is a soft check and does not affect the BLOCK decision.

### Independent recomputations

- Q3: `q3_raw/derive_q3.py` → committed raw outputs/mapping → all reported authority values reproduced.
- Q1: `paired_raw_108.json` + `admission_108.json` → pair by `(system, member)` → Student-t summaries reproduced.
- XRD control: raw `.txt`/`.mdi` → `xrd_protocol_kernel.analyse_single` → DOC 49.030543–65.218597%.

### Recommendation to Claude Science

- Do not request barrier extraction/publication or publish Q3/XRD claims from this snapshot. Commit the minimal document/provenance repairs and their negative regression fixtures, then request a fresh fixed-commit audit.

### Forbidden until closure

- `publish_claim` for Q2 barrier extraction, Q3 citability-dependent statements, and the unindexed XRD passivator conclusions.

### Required next report

- New commit SHA; disposition for F-019/F-022/F-023; corrected staging and current-status artifacts with hashes; canonical-index row for XRD; and clean-clone outputs for the added regressions.

### Execution declaration

- Codex repository changes: NONE to the Science Repository.
- Codex remote/HPC/GPU/instrument actions: NONE.
