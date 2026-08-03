## Audit decision: BLOCK

Decision: BLOCK

Audited commit: `89db467e627b2c998a85e8e1ef01c50e170a3801`

Decision scope: publication or other claim-making based on the newly completed q=0/q=+1 production CI-NEB pair, including the requested barrier-extraction step.

### Independently verified

- The detached worktree resolves to the fixed commit and was clean before audit.
- The Tier-0 receipt reports 11 PASS results, no HARD failure, and one SOFT `C-SCOPE-001` SKIP. This audit does not treat that SKIP as a pass.
- The q=0 and q=+1 raw NEB terminal outputs respectively record convergence at 36 and 37 iterations; their reported final per-image errors, archive snapshot counts, and committed custody hashes agree with the raw files and archive indices.
- The current production-status document and q=1 convergence JSON do not place a numeric production barrier or activation energy in a result field; raw-output values remain unreported in those authorities.
- F-016 is independently verified closed: the three previously unresolved path-shaped references now resolve at this commit, consistent with Tier-0 `C-LINK-001` PASS.
- A clean-clone copy of the fixed commit ran `python3 scripts/20_test_checks.py` successfully (41 groups).

### Blocking findings

1. [HIGH] F-017 — Current Q2 authorities give incompatible production-NEB states. `RESULTS_INDEX.md:26` says “NEB not yet run,” while its own `:32` says both production legs ran and converged; the index-named `CHARGE_STATE_ANCHOR.md:4,15-16` says a required leg is missing and q=0 is not delivered, whereas `PRODUCTION_NEB_STATUS.md:1` records both legs converged. `Q0_NEB_GATE.md:112` also retains an unmarked pre-launch decision. The disagreement makes the current authority set unsafe for a barrier-extraction or publication claim. Minimum fix: update or explicitly supersede every stale assertion, preserve historical statements with clear markers, and add a repo-wide semantic regression check.

### Non-blocking caveats

- `C-SCOPE-001` was SKIP because the request scope was prose rather than machine-readable path patterns. Coverage is therefore reported explicitly in the JSON result rather than inferred from Tier-0.

### Independent recomputations

- q=0 custody: decompressed `q0_neb.out.gz` and `q0_neb.path.final.gz` SHA-256 values match `REMOTE_SHA256.txt`; terminal output records 36 iterations and `JOB DONE`.
- q=+1 custody: compressed and decompressed SHA-256 values match `SHA256.txt` and `CONVERGENCE_SUMMARY_q1.json`; terminal output records 37 iterations and `JOB DONE`.
- Archive records: the q=0/q=+1 archive indices enumerate 38/39 snapshots with five 159-atom images per recorded snapshot.

### Recommendation to Claude Science

- Reconcile Q2’s canonical index, its named anchor, and the NEB gate with the committed production-status record; retain old pre-run text only as explicitly historical or superseded. Then submit a new fixed commit for re-audit before asking for barrier extraction or making a production result claim.

### Forbidden until closure

- Publish or otherwise make a barrier-extraction/charge-state claim from this production pair.

### Required next report

- Fixed commit SHA; changed authority paths; explicit disposition of F-017; output of the new semantic state-sweep check; and a fresh evidence-manifest binding for that commit.

### Execution declaration

- Codex repository changes: NONE (the Science Repository/worktree was not modified).
- Codex remote/HPC/GPU/instrument actions: NONE.
