## Audit decision: BLOCK

Decision: BLOCK

Audited commit: `bc98bda31b8aaf4836e38b815ed66f90ef341fd3`

Decision scope: publication claims relying on this fixed snapshot. This opinion applies only to the audited commit.

### Independently verified

- Tier-0 reports every HARD check as `PASS`; C-SCOPE-001 is the sole `SKIP` and is SOFT.
- F-022 is independently closed: the current q=+1 staging manifest is `SUBMITTED_AND_COMPLETED`; the four current source files exist and their raw-byte SHA-256 values match its recorded values. The earlier blocked record is explicitly retained as historical.
- F-023 is independently closed: `RESULTS_INDEX.md` now has a current QX row that names the English/Chinese passivator authorities, raw XRD data, summary metrics, analysis code, current dispositions, and the no-efficacy-claim boundary.

### Atomic claims checked

| Claim | Evidence / check | Status |
|---|---|---|
| q=+1 production-input custody is reproducible | current manifest paths and SHA-256 values | VERIFIED |
| live XRD conclusion is navigable from the canonical index | QX row and named authority/raw/code locators | VERIFIED |
| passing regression receipts state the passing predicate truthfully | clean-copy group-41 and group-44 receipts plus `expect()` | BLOCKED / F-024 |

### Blocking findings

1. [HIGH] F-024 — the current regression guard prints a violation proposition after a passing predicate. `expect()` prints the same failure-oriented message on both branches. Thus group 41 reports that the historical count is “not marked historical” even though its predicate accepted the explicit historical marker; group 44 likewise reports current sources as missing after accepting their presence. This makes a green human-readable receipt untrustworthy as evidence of what was actually checked. Minimum fix: commit the submitted success-branch-message/fixture repair (or equivalent), then demonstrate both accepted and rejected fixture receipts in a clean clone.

### Non-blocking caveats

None.

### Independent recomputations

- F-022: current q=+1 manifest file paths → raw-byte SHA-256 → all four recorded digests match.
- F-023: canonical index QX row → authority/raw/results/code locators → all required current-navigation elements present.
- F-024: clean-copy `scripts/20_test_checks.py` → group 41/44 output → passing rows retain failure-oriented wording.

### Recommendation to Claude Science

- Preserve the F-022 and F-023 repairs; both are closed at this commit.
- Submit the F-024 receipt-branch repair and its committed marked/unmarked fixtures, then request re-audit of the new commit.

### Forbidden until closure

- `publish_claim`: do not present a green regression receipt as a truthful verification record until F-024 is fixed and independently re-audited.

### Required next report

- Repair commit SHA; clean-clone command and exit code; paths to accepted/rejected fixtures; exact group-41 and group-44 receipts.

### Execution declaration

- Codex repository changes: NONE to the Science Repository.
- Codex remote/HPC/GPU/instrument actions: NONE.
- Audit artifacts were written only in this cycle directory.
