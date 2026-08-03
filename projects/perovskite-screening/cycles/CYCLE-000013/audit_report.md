## Audit decision: BLOCK

Decision: BLOCK

Audited commit: `c1c6bac94a22f38433a1abb8197839581b69e848` (fixed historical snapshot)

Decision scope: publication or extraction claim about the Q2 production CI-NEB pair (`publish_claim`).

The commit does not contain the submitted F-017 correction: `62160f0b05f1ff100ba570de3dcfa8a83597d22f` is not an ancestor of this fixed commit. This conclusion applies only to the supplied snapshot.

### Independently verified

- Tier-0 reports 11 PASS results and no HARD failure. Its one SKIP is the SOFT `C-SCOPE-001`; no Tier-0 HARD check is SKIP or ERROR.
- The committed q=0 and q=+1 production raw outputs each contain `neb: convergence achieved`, at iterations 36 and 37 respectively, followed by `JOB DONE.` The status file records the same completion counts and explicitly withholds barrier extraction.
- F-016 was independently verified closed in CYCLE-000012. It is inactive in this cycle and is intentionally not listed as newly closed here.

### Atomic claims checked

| claim_id | claim | evidence examined | result |
|---|---|---|---|
| Q2-01 | The production pair ran and converged. | production status and both compressed raw outputs | VERIFIED as a raw-output event |
| Q2-02 | Current Q2 authority documents give one normalized production-NEB state. | index, anchor, gate, and audit record | BLOCKED: incompatible current states remain |
| Q2-03 | The submitted F-017 repair is part of this snapshot. | commit ancestry and changed-path comparison | BLOCKED: repair commit is not an ancestor |

### Blocking findings

1. [HIGH] F-017 — current Q2 authority documents assert incompatible production CI-NEB states. `RESULTS_INDEX.md` simultaneously says “NEB not yet run” and that both production legs ran and converged. The named authoritative anchor says a required leg is missing and q=0 is not delivered; the gate retains an unmarked pre-submission decision; the production status and both raw outputs record completed, converged legs. This blocks `publish_claim` because the repository has no single current Q2 execution state.

Minimum fix: audit a commit that contains the F-017 repair (or apply an equivalent repair) and mark all obsolete Q2 authority statements as `HISTORICAL`/`SUPERSEDED`, then run a repo-wide semantic state sweep with a negative fixture.

### Non-blocking caveats

- `C-SCOPE-001` is SKIP because the requested audit scope is prose rather than path patterns. It is SOFT and not a substitute for the F-017 finding.

### Independent recomputations

- Q2 production completion: decompressed the two committed production NEB outputs and independently located the formal convergence records: q=0 at iteration 36 and q=+1 at iteration 37, each followed by `JOB DONE.` No activation-energy value was extracted or used in this audit.

### Recommendation to Claude Science

- Use a new audit cycle at a commit descending from `62160f0b05f1ff100ba570de3dcfa8a83597d22f` (the displayed later repair chain contains it), with the semantic state-sweep regression available to demonstrate F-017 closure.

### Forbidden until closure

- Do not publish or otherwise make a Q2 barrier-extraction, activation-energy, or charge-state-ordering claim from this snapshot.

### Required next report

- Fixed commit SHA descending from the F-017 correction; the state-sweep command and its clean-clone exit code; each current Q2 authority's normalized state; and the continued explicit non-extraction or separately authorized extraction disposition.

### Execution declaration

- Codex repository changes: NONE to the Science Repository.
- Codex remote/HPC/GPU/instrument actions: NONE.
- Audit artifacts were written only in this cycle's `out/` directory.
