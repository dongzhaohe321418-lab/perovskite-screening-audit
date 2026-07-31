## Audit decision: BLOCK

Decision: BLOCK

Audited commit: `4aed10a97d4858ef7b18dea940e6bf66294e2849` (fixed snapshot only)

Decision scope: publication of scientific claims. The Q3 repair findings F-012 and F-013 are independently verified closed. Publication remains blocked solely for the unmarked, contradicted XRD crystallinity range below.

### Independently verified

- Fixed commit identity and clean detached-clone execution: Q3 derivation and the 39-group regression suite both exited 0.
- F-012: direct parsing of committed P1/P2 raw outputs independently gives VBM-referenced `+75.8 meV`, semicore-aligned `+52.1 meV`, and semicore shift `-45.0 meV`. Both Q3 authorities carry those values.
- F-013: the Q3 canonical row now states that raw records are committed and recomputable; the only retained “not committed / cannot be independently reproduced” text is explicitly retracted. A repository-wide sweep found no other live occurrence of those legacy assertions.
- Objective 2 raw paired rows reproduce GA `n=11, mean +6.8 meV, sd 47.4 meV` and Sr `n=12, mean -4.3 meV, sd 59.6 meV`.
- Tier-0 result is accepted as machine truth: 11 PASS, no FAIL/ERROR, and one SOFT scope SKIP.

### Atomic claim verification

| Claim | Evidence / independent recomputation | Status |
|---|---|---|
| Q3 alignment figures are derivable from committed raw data | P1/P2 QE outputs, direct parser, and `q3_raw/derive_q3.py` | VERIFIED |
| Q3 raw-provenance state is internally consistent | `RESULTS_INDEX.md` Q3 row and three named authorities | VERIFIED |
| Objective 2 headline paired values match raw records | `paired_raw_108.json` joined by member and system | VERIFIED |
| XRD control DOC is 49–65% under current protocol | Raw `.txt` + `.mdi` recomputed via `xrd_protocol_kernel.analyse_single`; `summary_metrics.csv` | VERIFIED |
| XRD README Section 2's 46–60% DOC is current | `xrd/README.md:102` versus the current recomputation and same document's 49–65% statements | BLOCKED |

### Blocking findings

1. [HIGH] F-014 — Unmarked XRD DOC range is stale and contradicts the committed recomputation.
   `xrd/README.md:102` asserts 46–60%, while its summary table (`:31`) and limitations (`:297`) assert 49–65%. The same document records at `:366–367` that the background-model correction shifted the range from 46–60% to 49–65%, but the Section 2 assertion is not marked historical, superseded, or retracted. The committed current source `xrd/results/summary_metrics.csv` gives 49.03075193872934–65.21878625874905%; an isolated raw-data recomputation returned 49.030543–65.218597%. This leaves two incompatible current numerical claims in an authority document.

   Minimum fix: replace or explicitly mark the 46–60% Section 2 range as superseded, regenerate the README from the current result, and add the proposed regression check below.

### Non-blocking caveats

- Tier-0 C-SCOPE-001 is SOFT/SKIP because the declared scope is prose rather than machine-readable path patterns. It is not a passing check and is not a blocker.

### Independent recomputations

- Q3 alignment: parsed raw P1/P2 eigenvalues and each cell's VBM; applied the committed convention `defective − aligned pristine`, with the mean of the lowest 32 bands as the semicore reference. Result: `+75.8`, `+52.1`, `-45.0 meV`.
- Objective 2: joined raw rows on recorded `(member, system)` keys and subtracted the same-member undoped barrier. Results match the published GA/Sr n, means, SDs, and listed individual values.
- XRD: used the committed control scan and `.mdi` metadata with the current `xrd_protocol_kernel.analyse_single` implementation. Result: DOC range 49.030543–65.218597%.

### Recommendation to Claude Science

- Correct the unmarked 46–60% statement, preserve it as a named superseded value if historical context is needed, and add `C-XRD-DOC-001`: regenerate the control DOC range from the committed raw `.txt`/`.mdi` using `xrd_protocol_kernel`, then require every unmarked DOC range in `xrd/README.md` to round to that same range. A fixture retaining unmarked 46–60% while the derivation returns 49–65% must fail.

### Forbidden until closure

- `publish_claim` for the XRD control's absolute degree-of-crystallinity range.

### Required next report

- Fixed commit SHA; regenerated XRD output; raw recomputation command and output; the exact supersession/retraction marker; and a clean-clone negative fixture for `C-XRD-DOC-001`.

### Execution declaration

- Codex repository changes: NONE (science worktree unchanged).
- Codex remote/HPC/GPU/instrument actions: NONE.
