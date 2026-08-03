## Audit decision: PASS

Decision: PASS

Audited commit: `62160f0b05f1ff100ba570de3dcfa8a83597d22f`

Decision scope: independent re-audit of F-017 and the fixed snapshot's current result, evidence, gate, and status records. This opinion applies only to this commit.

### Independently verified

- Tier-0 is bound to the same commit and records 11 PASS results, no FAIL, no ERROR, and no HARD skip. Its sole SKIP is the SOFT scope-pattern check (`C-SCOPE-001`), which is not treated as a pass.
- F-017 is closed at this snapshot. `RESULTS_INDEX.md` states that both production legs converged and names the current production-status record. `CHARGE_STATE_ANCHOR.md` carries a top-of-file **SUPERSEDED AS CURRENT STATE** banner that scopes its old missing/not-delivered assertions to the historical 2026-07-25 state. `Q0_NEB_GATE.md` preserves its former open-decision text inside an explicit HISTORICAL wrapper.
- The current raw records independently support the current Q2 execution state: `q0_neb.out.gz` says `neb: convergence achieved in 36 iterations` followed by `JOB DONE`; the corresponding q=+1 output says 37 iterations followed by `JOB DONE`.
- A clean detached clone at this commit ran `python3 scripts/20_test_checks.py` successfully (42 groups). In an isolated negative fixture, changing the F-017 supersession banner so it no longer matched the semantic sweep made group 42 fail with exit code 1.
- Independent recomputation from `paired_raw_108.json` produced the current Q1 summary after document rounding: GA n=11, mean +6.807240 meV, 95% Student-t CI [-25.005380, 38.619859]; Sr n=12, mean -4.310502 meV, CI [-42.184563, 33.563558].
- `q3_raw/derive_q3.py` completed in the isolated clone and reproduced its recorded custody, mapping, cosine, and alignment values; Q3 remains explicitly NOT CITABLE in the canonical index and was not promoted by this audit.

### Blocking findings

None.

### Non-blocking caveats

- `C-SCOPE-001` is SOFT/SKIP because the audit scope is prose rather than machine-readable path patterns. It creates no unreported HARD failure and does not alter this decision.

### Independent recomputations

- Q2 execution: decompressed the two committed production NEB outputs and verified their convergence and terminal markers.
- Q1 statistics: recomputed paired differences, sample standard deviations, and Student-t intervals directly from the 108-row raw ledger.
- Q3 provenance: executed the committed derivation in an isolated clone; the result's repository-declared NOT CITABLE status remains in force.

### Recommendation to Claude Science

- Record the verified closure of F-017. If barrier extraction is sought, obtain and record the separate required `check_action` ALLOW; this PASS is an audit opinion, not that authorization.

### Forbidden until closure

- Do not present a Q2 barrier value, charge-state ordering, or Tyagi-ordering comparison until the repository's separately required barrier-extraction/publication gate has an explicit ALLOW record.

### Required next report

- For any extraction or publication request: exact action authorization, the extracted values and raw-data derivation path, input/output hashes, and the resulting updated canonical-status records.

### Execution declaration

- Codex repository changes: NONE to the Science worktree.
- Codex remote/HPC/GPU/instrument actions: NONE.
