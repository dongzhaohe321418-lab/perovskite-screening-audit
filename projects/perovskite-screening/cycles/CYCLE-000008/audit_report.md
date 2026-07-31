# Independent scientific audit report

Decision: PASS

## Audit decision: PASS

Audited commit: `af0dc58713b9bcf675fb324a262024f39127f8a7`  
Decision scope: Re-audit of F-015 at its submitted fix commit; this decision applies only to this fixed snapshot.

### Atomic claims and verification

| Claim | Verification | Status |
|---|---|---|
| The suite now emits 41 numbered groups. | Enumerated the numbered `print("\\n[...")` statements in `scripts/20_test_checks.py`. | VERIFIED (41) |
| Live suite-count declarations agree with the source. | Read `README.md`, `results/objective2/CURRENT_STATUS.md`, and `EXPERIMENT_AUDIT.md`. | VERIFIED (41 in each) |
| The earlier 36-group statement is not presented as current. | Read the F-007 section of `AUDIT_CORRECTIONS_CYCLE1.md`. | VERIFIED; it opens with `HISTORICAL RECORD` and an explicit supersession note. |
| The regression protection is executable. | Ran `python3 scripts/20_test_checks.py` in an isolated copy of the fixed worktree. | VERIFIED; exit 0, including group [41]. |

### Independently verified

- The audited worktree resolves to the required commit and was clean when inspected.
- The five-path submitted diff contains the correction record, all three live suite-count declarations, and the regression suite itself.
- Tier-0 reports no HARD FAIL, SKIP, or ERROR. Its sole SKIP is `C-SCOPE-001`, which is SOFT.

### Blocking findings

None.

### Non-blocking caveats

None for this focused re-audit.

### Independent recomputations

- Regression-suite count: source enumeration = 41; all current declarations = 41.
- Executable verification: `python3 scripts/20_test_checks.py` completed successfully in an isolated copy and reported all 41 groups, including the F-015 regression.

### Verified closure

- F-015 is independently verified closed. Its 36-group statements are explicitly historical/superseded, current declarations are 41, and regression group [41] enforces the distinction.

### Recommendation to Claude Science

- Record F-015 as closed for this commit. No audit finding blocks the scoped re-audit result.

### Forbidden until closure

- No new prohibition is created by this report.

### Required next report

- For any later suite-count change, provide the changed source, every live declaration, and a clean-copy regression transcript.

### Execution declaration

- Codex repository changes: NONE (the science worktree was read only).
- Codex remote/HPC/GPU/instrument actions: NONE.
