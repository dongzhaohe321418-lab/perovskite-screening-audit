## Audit decision: BLOCK

Decision: BLOCK

Audited commit: `b7de47840a74d0e6fc5321912e54f4d05fbab7f1` (fixed snapshot only)

Decision scope: Q3 provenance/authority claims and the Objective 1 gate that cites them; no production submission or publication claim may rely on Q3 until the findings below close.

### Independently verified

- The detached worktree resolves to the fixed commit and was clean.
- In an isolated clean clone, `python3 results/objective1/dft/charge_relaxed/q3_raw/derive_q3.py` exited 0. It independently rechecked six custody hashes, rebuilt the 160-to-159 mapping from raw QE site lists, and recomputed the Q3 energy, moment, cosine, IPR, and alignment outputs.
- In that clean clone, `python3 scripts/20_test_checks.py` exited 0 and completed 38 groups. This agrees with, and does not supersede, Tier-0 `C-TEST-001: PASS`.
- The q0_final raw QE output reports energy error `9.8E-05 Ry`, gradient error `1.6E-03 Ry/Bohr`, and BFGS convergence in 11 SCF cycles / 10 BFGS steps. The prior F-011 plateau statement is struck and explicitly superseded.

### Blocking findings

1. [HIGH] F-012 — Q3 authority alignment values do not reproduce from the committed derivation.

   `P1_REFERENCE_AUDIT.md:47-48` and `Q0_RESOLVED.md:16` quote VBM-referenced `+75.9 meV` and semicore-aligned `+52.1 meV`. The committed derivation, which both documents claim recomputes every quoted value, prints VBM-referenced `-75.8 meV` and semicore-referenced `-33.5 meV`. A reversal of the VBM subtraction convention can explain its sign but not the semicore magnitude discrepancy. The two authoritative numerical records therefore do not identify one reproducible calculation.

   Minimum fix: state one explicit alignment definition, regenerate the two authority documents from that definition and raw outputs, and add the proposed regression check.

2. [HIGH] F-013 — The canonical Q3 index simultaneously says raw evidence is absent and committed.

   `RESULTS_INDEX.md:36-46` currently says Q3 raw inputs are not committed and results cannot be reproduced, while its own lines 51-55 say the complete Q3 raw record is committed and `derive_q3.py` exits 0. The three index-named authority documents also state at their opening banners that the records are now committed. This is a current status/provenance contradiction, not a historical annotation.

   Minimum fix: reconcile the Q3 row to one truthful present provenance state. It may remain NOT CITABLE while F-012 is resolved, but it must not retain the unmarked assertion that raw evidence is absent.

### Non-blocking caveats

- Tier-0 `C-SCOPE-001` is SOFT and `SKIP`: the audit request declares a prose scope rather than machine-readable path patterns. No HARD Tier-0 check was skipped or errored.

### Independent recomputations

- Q3 raw chain: six decompressed raw outputs → SHA-256 custody check → PASS.
- Q3 state mapping: raw 160/159 QE site lists → mutual minimum-image same-species map → 159 pairs and one unmatched iodine → PASS.
- Q3 current derivation output: raw P1/P2/projwfc/ELAS/POL → `derive_q3.py` → cosine `0.9757`, effective atoms `35.6/38.3`, alignment output `-75.8/-33.5 meV`. The latter conflicts with the authority-table values cited in F-012.
- q0_final convergence: compressed QE output → final formal convergence block → PASS.

### Previously open findings independently verified closed

- F-006: committed Q3 raw inputs, chain-of-custody records, mapping artifact, and an executable clean-clone derivation are present and execute successfully. This closes the prior missing-input/transformation defect; F-012 is a distinct current numerical-record defect.
- F-008: each authority named by the demoted Q3 index row (`Q0_POLARON_EXCLUDED.md`, `Q0_RESOLVED.md`, and `P1_REFERENCE_AUDIT.md`) carries the required Q3 provenance/demotion marker; regression group 37 discovers those authorities from the index.
- F-011: the conflicting q0_final plateau text is explicitly superseded, while the raw convergence block and current gate/index status agree.

### Recommendation to Claude Science

- Preserve Q3 as NOT CITABLE, repair the conflicting alignment numbers and canonical provenance wording from the committed raw derivation, then submit a new commit for clean-clone re-audit. This is an audit recommendation, not an execution authorization.

### Forbidden until closure

- `submit_production_job` where condition 3 depends on the Q3 authority record.
- `publish_claim` relying on Q3 alignment/provenance statements.

### Required next report

- New fixed commit SHA; normalized alignment definition and regenerated authority values; canonical Q3 row reflecting raw evidence actually present; regression output demonstrating failure for the current mismatch and success after repair; Claude disposition for F-012 and F-013.

### Execution declaration

- Codex repository changes: NONE to the Science Repository.
- Codex remote/HPC/GPU/instrument actions: NONE.
