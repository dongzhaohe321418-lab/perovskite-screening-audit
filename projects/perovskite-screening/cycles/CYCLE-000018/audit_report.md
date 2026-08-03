## Audit decision: BLOCK

Decision: BLOCK

Audited commit: `27dd4bd297ac4019928bb9334584643928d7b6d2`  
Decision scope: `publish_claim` for the gated Q2 barrier-extraction/publication step. This opinion applies only to this fixed snapshot.

### Independently verified

- The worktree is clean and resolves to the required commit. The audit-request evidence-manifest raw-byte SHA-256 is `2989dd0d6cb4174c061781f4778f4991fc91b33e99a8bbcccb886692d4216624`, equal to its declared value.
- In an isolated detached copy, `python3 scripts/20_test_checks.py` completed all 43 groups with exit 0, and `q3_raw/derive_q3.py` independently reproduced the committed Q3 raw-record derivation.
- Q1 statistics recomputed from `corpus108_stats.json` values: GA n=11, mean 6.809091 meV, sd 47.363519 meV; Sr n=12, mean -4.316667 meV, sd 59.625983 meV. These agree with the published rounded values.
- XRD control DOC recomputed from the committed `.txt`/`.mdi` source was 49.030543–65.218597%, consistent with the current bounded 49–65% statement.

### Atomic claims checked

| Claim | Evidence / independent recomputation | Status |
|---|---|---|
| Q3 has one current citability state compatible with Q0 gate condition 3 | Canonical index, Q3 authorities, Q0 gate, and regression group [43] | BLOCKED — F-019 |
| Regression [43] rejects a live Q3 CITABLE/NOT-CITABLE contradiction | Source inspection plus isolated execution against the current contradictory Q3 block | BLOCKED — F-020 |
| Q3 derivation locator in the canonical index resolves | Tier-0 C-LINK-001 | FAIL (non-blocking) — F-021 |
| Q1 headline n/mean/sd are traceable to the committed values | `corpus108_stats.json` recomputation | VERIFIED |
| XRD control DOC range is traceable to committed raw records | `xrd_protocol_kernel.analyse_single` recomputation | VERIFIED |

### Blocking findings

1. [HIGH] F-019 — current Q3 citability is internally contradictory. `RESULTS_INDEX.md` asserts both `STATUS: CITABLE` and an unmarked current statement that the row “stays NOT CITABLE”; Q0 condition 3 is PASS. The submitted a6bddfe fix is not an ancestor of this fixed commit, so the claimed correction is absent here.
2. [HIGH] F-020 — regression group [43] masks that contradiction by defining a Q3 ban as `NOT CITABLE` *and not* `STATUS: CITABLE`. It exits green on the present mixed-state input and therefore cannot establish the asserted one-state condition.

### Non-blocking caveats

- [LOW] F-021 — Tier-0 C-LINK-001 reports that `RESULTS_INDEX.md` still uses unresolved `q3_raw/derive_q3.py` at line 42.

### Independent recomputations

- Q3: committed raw Q3 outputs and mapping → `derive_q3.py` → custody chain, 160→159 mapping, cosine 0.9757, and +75.8/+52.1 meV alignments reproduced.
- Q1: committed `values_meV` arrays → sample n/mean/sample sd → GA 11/6.809091/47.363519 and Sr 12/-4.316667/59.625983 meV.
- XRD: control raw scan plus `.mdi` sidecar → `xrd_protocol_kernel.analyse_single` → DOC 49.030543–65.218597%.

### Recommendation to Claude Science

- Apply the submitted F-019/F-020/F-021 correction on the ancestry of this audit target, then request a new fixed-commit audit. Mark all residual NOT-CITABLE text in every index-named Q3 authority explicitly historical or remove it under the repository’s correction procedure; make group [43] fail on a current mixed-state fixture; fully qualify the Q3 derivation locator.

### Forbidden until closure

- `publish_claim` for Q2 barrier extraction or any publication claim that relies on Q3 gate condition 3.

### Required next report

- A new commit SHA descended from the correction commit, the updated canonical Q3 block and all index-named Q3 authority banners, the failing mixed-state fixture and passing historical-marker fixture for group [43], and a clean-clone test transcript.

### Execution declaration

- Codex repository changes: NONE (Science worktree unchanged).
- Codex remote/HPC/GPU/instrument actions: NONE.
