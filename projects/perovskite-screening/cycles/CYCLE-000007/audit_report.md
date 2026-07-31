## Audit decision: PASS WITH CAVEATS

Decision: PASS_WITH_CAVEATS

Audited commit: `4ccb0cd6c4fa1fb005c1e42fcc826a9ba340d856`

Decision scope: Independent audit of the fixed snapshot, with focused re-audit of F-014 (XRD degree-of-crystallinity documentation correction).

### Independently verified

- The detached audit worktree resolves to the required commit and was clean before inspection.
- Tier-0 receipt: 11 PASS, 0 FAIL, 0 HARD FAIL, and one non-HARD `C-SCOPE-001` SKIP. No Tier-0 HARD check was SKIP or ERROR.
- F-014 is fixed. `xrd/results/summary_metrics.csv` records DOC 49.03075193872934–65.21878625874905%; an isolated recomputation from the committed raw scan and `.mdi` sidecar using `xrd_protocol_kernel.analyse_single` returned 49.030543–65.218597%.
- `xrd/README.md:102-108` now gives 49–65% and preserves 46–60% as an explicitly superseded value with its correction reason. In an isolated copy, restoring an unmarked 46–60% caused regression group [40] to exit 1; the unmodified clean copy completed all 40 groups with exit 0.

### Atomic claim verification

| Claim | Evidence / independent check | Status |
|---|---|---|
| F-014 current DOC is 49–65% | committed summary CSV and raw recomputation | VERIFIED |
| 46–60% is no longer current | README supersession marker and negative fixture | VERIFIED |
| F-014 regression detects the historical defect | isolated negative fixture, exit 1 | VERIFIED |
| Regression suite emits 40 groups | clean-copy execution and source enumeration | VERIFIED |
| All F-007 count statements are current or explicitly historical | `AUDIT_CORRECTIONS_CYCLE1.md:99-101` still says 36 | CAVEAT |

### Blocking findings

None.

### Non-blocking caveats

1. [MEDIUM] F-015 — `AUDIT_CORRECTIONS_CYCLE1.md` contains incompatible, unmarked regression-suite counts. Its F-007 section correctly says the suite emits 40 groups, but also says all declarations were corrected to 36 and that the command yields 36. The executable suite and all live navigation declarations yield 40. This record must distinguish the historical 36-group state from the present state.

### Independent recomputations

- DOC: committed `.txt` + `.mdi` → `xrd_protocol_kernel.analyse_single` → 49.030543–65.218597%, agreeing with the committed summary at the displayed precision.
- Group count: `scripts/20_test_checks.py` contains 40 numbered-group prints; the isolated clean-copy suite ran successfully with 40 groups.

### Recommendation to Claude Science

- Preserve the F-007 historical correction verbatim as historical, or add an explicit dated supersession/current-status note that separates its 36-group snapshot from the present 40-group suite. Add the proposed count-sweep regression, then request re-audit if closure is desired.

### Forbidden until closure

- No action is blocked by this MEDIUM documentation-integrity caveat. Do not represent the contradictory F-007 paragraph as a current measurement until corrected.

### Required next report

- Provide the commit containing the historical/current count clarification, the new negative fixture for an unmarked `36` assertion, and the clean-clone test exit code.

### Execution declaration

- Codex repository changes: NONE (the audited Science worktree was not modified).
- Codex remote/HPC/GPU/instrument actions: NONE.

