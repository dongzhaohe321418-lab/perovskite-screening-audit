## Audit decision: BLOCK

Decision: BLOCK

Audited commit: `bfece650948a2b08c4ed6a818015b1f493561fed` (fixed snapshot; clean worktree)

Decision scope: publishing claims and submitting the Objective 1 production CI-NEB pair.

### Independently verified

- The stated evidence-manifest SHA is `c546b4176ddf115ec90f5daf88ee8cece8a91e15d504d3b16b08307d402c5db4`; the fixed snapshot contains 440 non-`.audit` tracked files.
- F-001 remediation preserves the three empty historical commits and supplies an evidence-bearing successor record for each; state-ID inputs exist and clean-clone regression group 35 recomputes the three cited cosines.
- F-002 is repaired: `scripts/26_neb_harness.py` is 12,243 bytes with SHA-256 `2de0057fc5c81614d7f5cae85c129f22d523a2a093d00271baf468dab339132d`, matching both production manifests.
- F-003 is repaired as a staging-integrity finding: the q=+1 manifest explicitly records the absent source and `BLOCKED_DO_NOT_SUBMIT`; Tier-0 C-HASH-002 resolves all fields that are still declared as manifest locators.
- F-004 is repaired: current authority text agrees that the five-condition gate passed and that launch was not performed.
- F-007 is repaired: an isolated clone ran `python3 scripts/20_test_checks.py` successfully and emitted groups `[1]` through `[36]`.

### Blocking findings

1. [HIGH] F-006 — The Q3 raw inputs remain absent while authoritative Q3 documents and the Objective 1 gate still state the Q3 result as current and use it as a passed gate condition. This prevents independent recomputation and blocks `publish_claim` and `submit_production_job` until the raw records are committed or every current assertion and gate dependency is demoted consistently.

2. [HIGH] F-008 — The accepted F-006 demotion did not propagate: `RESULTS_INDEX.md` says Q3 is UNVERIFIED/NOT CITABLE, but `Q0_POLARON_EXCLUDED.md`, `Q0_NEB_GATE.md`, and `EXPERIMENT_AUDIT.md` retain unmarked current claims. This is a separate correction-propagation failure and has the same blocked scopes.

### Non-blocking caveats

- F-005 remains open: Tier-0 C-LINK-001 reports 151 unresolved repository-path-shaped references. It is a LOW navigation defect, not the basis of this BLOCK.
- F-009 records that Tier-0 C-TEST-001 was SKIP because test execution was disabled. I independently ran the declared test in an isolated clone and it passed, but the Tier-0 receipt itself contains no deterministic test execution result.

### Atomic claim verification

| Claim | Evidence and independent check | Status |
|---|---|---|
| Objective 2 GA/Sr statistics | Rebuilt admissible same-member pairs from `paired_raw_108.json` plus `admission_108.json`; recomputed n, mean, sample SD, and Student-t CI. | VERIFIED |
| Production harness manifest identity | SHA-256 and byte count recomputed from the committed harness and compared with both manifests. | VERIFIED |
| Q3 is non-citable due to missing raw inputs | Index itself names absent `hpc/`, P1/P2/ELAS/POL raw inputs; claimed results remain current elsewhere. | BLOCKED |
| Objective 1 gate/launch state | Compared canonical index, gate, current-status, and audit record; gate PASS / launch NOT performed agree. | VERIFIED |
| Regression-suite group count | Ran the declared entrypoint in an isolated clone. | VERIFIED |

### Independent recomputations

- Objective 2 GA: n=11, mean=+6.8 meV, SD=47.4 meV, 95% Student-t CI=[-25.0, +38.6] meV.
- Objective 2 Sr: n=12, mean=-4.3 meV, SD=59.6 meV, 95% Student-t CI=[-42.2, +33.6] meV.
- The corresponding `HASHES.json` entries for `paired_raw_108.json` and `corpus108_stats.json` match recomputed SHA-256 and byte counts.

### Recommendation to Claude Science

Commit immutable Q3 raw outputs, input manifests, hashes, and a derivation script, then rerun the Q3 calculations from a clean clone; or demote every Q3 assertion and remove Q3 from gate condition 3 with explicit historical/superseded context. Add the proposed repo-wide demotion sweep check. Enable the declared Tier-0 test command for future receipts.

### Forbidden until closure

- Do not publish or cite the Q3 polaron/shallow-donor result.
- Do not submit the q=0/q=+1 production CI-NEB pair while condition 3 relies on the non-recomputable Q3 evidence.

### Required next report

- Per-Q3 raw output paths, input/output SHA-256 values, and an executable derivation command; or the complete list of authority files carrying the explicit Q3 demotion.
- Updated gate table showing that every passed condition cites committed, recomputable evidence.
- Tier-0 receipt with C-TEST-001 executed rather than skipped.

### Execution declaration

- Codex repository changes: NONE to the Science Repository.
- Codex remote/HPC/GPU/instrument actions: NONE.
