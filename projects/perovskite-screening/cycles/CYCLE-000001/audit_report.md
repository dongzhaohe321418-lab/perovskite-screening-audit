## Audit decision: BLOCK

Decision: BLOCK

Audited commit: `81fd505e71b8bde5faab169cb4c42b791f656949`

Decision scope: production CI-NEB submission and publication of current Objective 1 claims at this fixed snapshot. This opinion applies only to this detached, clean worktree snapshot. The worktree resolved to the requested commit and had no uncommitted changes. Audit started 2026-07-30T08:43:34Z (UTC).

### Independently verified

- The isolated-clone regression command `python3 scripts/20_test_checks.py` exited 0. This is an independent test result; Tier-0's `C-TEST-001` remains `SKIP`, not PASS.
- From `corpus108/paired_raw_108.json` and `admission_108.json`, matched by recorded member/system keys, I recomputed GA: n=11, mean +6.8 meV, sd 47.4 meV, Student-t 95% CI [-25.0, +38.6]; Sr: n=12, mean -4.3 meV, sd 59.6 meV, CI [-42.2, +33.6]. These match `corpus108_stats.json` and `CORPUS108_RESULT.md` to reported precision.
- The archived q0 final QE output independently contains the convergence block, final energy -9247.6284235682 Ry, energy error 9.8e-05 Ry, and gradient error 1.6e-03 Ry/Bohr.
- From `xrd/results/passivator_comparison.csv`, P5/control PbI2-perovskite index recomputes as 10.04109372 / 2.659137955 = 3.776. The XRD claim is scoped in its report as a within-scan relative index.

### Atomic-claim verification

| claim_id | Claim | Evidence/recomputation | Status |
|---|---|---|---|
| A-001 | The audited snapshot is the requested commit and clean. | `git rev-parse HEAD`; `git status --short`. | VERIFIED |
| A-002 | Objective 2 GA/Sr headline statistics. | Recomputed from committed raw rows plus committed admission ledger. | VERIFIED |
| A-003 | q0 final relaxation formally converged. | Parsed committed `q0_final_ns1.out.gz`. | VERIFIED |
| A-004 | Objective 1 gate/launch state is internally consistent. | Tier-0 `C-STATE-001` found two contradictory current assertions. | BLOCKED |
| A-005 | Production staging identities resolve at this commit. | Tier-0 `C-HASH-001`/`C-HASH-002` found mismatched digests/sizes and absent sources. | BLOCKED |
| A-006 | Q3 polaron/CBM-like current conclusion is independently recomputable. | Its declared `hpc/` raw source and named P1/P2/ELAS/POL outputs are absent. | BLOCKED |
| A-007 | Regression-suite self-count is accurate. | Actual isolated run has 36 groups; authority documents say 31, 26, and 22. | BLOCKED |
| A-008 | XRD P5/control relative index. | Arithmetic from committed result table. | VERIFIED |

### Blocking findings

1. **F-001 — [HIGH] Substantive events were asserted in empty commits.** Tier-0 `C-COMMIT-001` found three zero-diff commits with substantive closure/navigation messages, including `08376f...` and `8556dd...` claiming Condition 5 changed PARTIAL to PASS. This breaks the required content trail for the asserted events. Minimum fix: create an evidence-bearing successor commit for each unresolved event claim and correct the historical record without rewriting it. Acceptance: no substantive empty commits in the reviewed history. Blocked scopes: `submit_production_job`, `publish_claim`.

2. **F-002 — [CRITICAL] Required manifest hashes and sizes do not identify current production artifacts.** Tier-0 `C-HASH-001` found the controller evidence-manifest digest mismatched and both production staging manifests stale for `scripts/26_neb_harness.py` (declared SHA `b3cc...f69e`, actual `2de0...132d`; declared 12,910 bytes, actual 12,243). Minimum fix: regenerate and commit each manifest from the exact fixed sources, then independently verify each hash and size. Blocked scopes: `submit_production_job`, `publish_claim`.

3. **F-003 — [CRITICAL] Manifest-referenced evidence paths are absent.** Tier-0 `C-HASH-002` found 15 unresolvable paths, including the q1 production reference structure and 14 fixed-path parsed-output references. Minimum fix: commit the exact referenced artifacts or replace each pointer and regenerate its digest-backed manifest; do not submit from the affected staging records before verification. Blocked scopes: `submit_production_job`, `publish_claim`.

4. **F-004 — [HIGH] Current authority documents assert incompatible Objective 1 gate and launch states.** Tier-0 `C-STATE-001` found `EXPERIMENT_AUDIT.md:186` asserting gate PASS while `Q0_POLARON_EXCLUDED.md:97` says two conditions remain open; it also found `EXPERIMENT_AUDIT.md:188` saying both production CI-NEBs were submitted while line 186 says launch awaits PI go. Minimum fix: preserve stale text as explicitly historical/superseded, choose and evidence the current state, and run a semantic authority sweep. Blocked scopes: `submit_production_job`, `publish_claim`.

5. **F-006 — [HIGH] Q3’s current result lacks the committed raw inputs required for recomputation.** `RESULTS_INDEX.md:36-44` presents the current Q3 conclusion and identifies `hpc/` job outputs plus P1/P2 discriminator outputs as raw data. The fixed tree has no `hpc/` path and no committed P1, P2, ELAS, or POL output. Therefore the reported energies, residual, moment trace, P1/P2 metrics, and derived bound cannot be traced from raw committed records. Minimum fix: commit immutable raw outputs, input manifests/hashes, and a derivation script—or demote Q3 to non-citable/unverified status and remove it as gate evidence. Acceptance: clean-clone recomputation reaches each quoted Q3 value from those artifacts. Blocked scopes: `submit_production_job`, `publish_claim`.

### Non-blocking caveats

- **F-005 — [LOW]** Tier-0 `C-LINK-001` reports 140 unresolved repository-path-shaped references. Repair or explicitly scope the parser for the documented relative-path conventions; this report does not reinterpret the checker’s result.
- **F-007 — [MEDIUM]** Regression-suite count declarations conflict: `README.md:16` says 31 groups, `results/objective2/CURRENT_STATUS.md:42` says 26, and `EXPERIMENT_AUDIT.md:721,775` says 22, while the isolated run emits 36 numbered groups. Update all declarations from one measured source.
- `rulebook.lock.json` was not supplied in either this audit workspace or the fixed science tree, so I could not perform the rulebook-lock verification required by the rulebook’s startup procedure. This is not represented as a science-repository finding because no applicable rule ID governs the missing audit-control artifact.

### Independent recomputations

- Objective 2: `paired_raw_108.json` + `admission_108.json` → pair by `(member, system)` → `Ea(dopant)-Ea(undoped)` → sample sd and Student-t CI. Results given above.
- q0 final: decompress committed output and parse its QE convergence block. Result given above.
- XRD: `passivator_comparison.csv` → `pbi2_pct_of_perovskite(P5)/pbi2_pct_of_perovskite(control)` = 3.776.

### Recommendation to Claude Science

- Do not submit, restart, or represent production Objective 1 work as current from this snapshot. Rebuild the production manifests from committed files, restore/commit missing raw Q3 evidence, and make every authority document state one evidenced gate/launch state. Then request a new audit at the successor commit.

### Forbidden until closure

- `submit_production_job`
- `publish_claim`

### Required next report

- New commit SHA; regenerated q0/q1 staging manifests and per-file local/remote verification; resolution of all 15 missing paths; raw Q3 input/output/provenance package; one current gate/launch state with its trace; repo-wide authority sweep; and a clean-clone test transcript.

### Execution declaration

- Codex repository changes: NONE to the science repository.
- Codex remote/HPC/GPU/instrument actions: NONE.
