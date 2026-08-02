## Audit decision: PASS WITH CAVEATS

Decision: PASS_WITH_CAVEATS

Audited commit: e967e47176f2eb06ec7843c94ec3f30f3929cff9

Decision scope: Evidence integrity, reproducibility, and current-document consistency for the fixed snapshot only. This is an audit opinion, not authorization to submit work, publish claims, alter protocols, or operate any instrument.

### Independently verified

- The isolated detached copy resolved to the fixed commit and was clean before audit commands. The Tier-0 receipt reports no HARD failures and no HARD skips/errors.
- `scripts/20_test_checks.py` completed successfully in the isolated copy, exercising 41 numbered regression groups.
- Q3's committed `derive_q3.py` completed successfully and rebuilt the quoted Q3 custody, state-mapping, cosine, IPR, alignment, and bounded discriminator values from committed records.
- Recalculation from `paired_raw_108.json` and `admission_108.json` gave GA n=11, mean 6.807240 meV, 95% CI [-25.005380, 38.619859], and Sr n=12, mean -4.310502 meV, 95% CI [-42.184563, 33.563558], agreeing with the rounded current result record.
- Recalculation from the committed XRD control `.txt`/`.mdi` through `xrd_protocol_kernel` gave DOC 49.030543–65.218597%, agreeing with the current 49–65% bounded statement and CSV record.
- Q2 does not quote barrier values: the production-status record says extraction is separately gated, while the committed q=0/q=+1 raw outputs contain `JOB DONE` and the committed q=1 convergence summary records all final image errors at or below 0.05 eV/Å.

### Atomic claim verification

| claim_id | assertion | independent check | status |
|---|---|---|---|
| C-001 | Q3 quoted authority values are reproducible from committed raw records | Executed `q3_raw/derive_q3.py` | VERIFIED |
| C-002 | Objective 2 paired summaries match the committed admission set and raw rows | Recomputed paired differences and Student-t intervals | VERIFIED |
| C-003 | Current XRD DOC range matches raw scan recomputation | Re-ran committed kernel on raw `.txt` plus `.mdi` | VERIFIED |
| C-004 | Q2 barrier ordering is not currently claimed | Inspected index and production-status record | VERIFIED |
| C-005 | Current path-shaped references resolve | Tier-0 C-LINK-001 | CAVEAT |

### Blocking findings

None.

### Non-blocking caveats

1. [LOW] Three current repository-path-shaped references do not resolve: `RESULTS_INDEX.md:32` omits the directory prefix for `PRODUCTION_NEB_STATUS.md`; `results/objective1/dft/charge_relaxed/PRODUCTION_NEB_STATUS.md:24` and `:26` omit the q0/q1 production subdirectories for their JSON records. Tier-0 C-LINK-001 records all three. This is a navigation defect only; it does not contradict the present underlying artifacts, which resolve at their documented production locations.

### Independent recomputations

- Q3: committed raw outputs and mapping inputs → `results/objective1/dft/charge_relaxed/q3_raw/derive_q3.py` → successful assertion of all quoted authority values.
- Objective 2: `paired_raw_108.json` + `admission_108.json` → admissible dopant-minus-undoped pairs and Student-t CI → GA 6.807240 meV / [-25.005380, 38.619859]; Sr -4.310502 meV / [-42.184563, 33.563558].
- XRD: committed control raw `.txt` + `.mdi` → `xrd_protocol_kernel.analyse_single` → DOC 49.030543–65.218597%.

### Recommendation to Claude Science

- Correct the three relative/repository paths reported in F-016, retain their current targets, and run the clean-clone regression suite before requesting a new navigation review. This is not an execution authorization.

### Forbidden until closure

- No additional prohibition is imposed by this audit. Existing repository/PI gates remain in force, including the separately gated Q2 barrier-extraction step.

### Required next report

- If the path corrections are made, provide the fixed commit, the three corrected locators, and clean-clone test output. Any later barrier-extraction request must separately provide the requested action, raw derivation, and controlling approval evidence.

### Execution declaration

- Codex repository changes: NONE (the audited Science worktree was not modified).
- Codex remote/HPC/GPU/instrument actions: NONE.
