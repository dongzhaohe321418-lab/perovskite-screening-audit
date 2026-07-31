## Audit decision: BLOCK

Decision: BLOCK

Audited commit: `746564b69191a91a41536bf0d9aa870220cda408`

Decision scope: independent record-integrity audit of all tracked scientific code, data, manifests, computed results, reports, XRD analysis, and current scientific claims at this fixed snapshot. This conclusion applies only to that snapshot.

### Independently verified

- The detached worktree resolves exactly to the audited commit and was clean when inspected.
- Tier-0 reports 11 PASS, no FAIL or ERROR, and one SOFT SKIP (`C-SCOPE-001`); no Tier-0 HARD failure is being re-reported here.
- In an isolated clone, `derive_q3.py` exited 0: all 6 cluster-custody uncompressed output hashes matched, P2 reproduced 6 iterations and zero final moment, ELAS reproduced 112.6 meV, and the POL last-point values reproduced 109.8 meV above delocalised and 2.8 meV fixed-geometry spin gain.
- An independent byte/hash check matched all 18 files in `q3_raw/INPUT_MANIFEST.json`.
- From `paired_raw_108.json` and `admission_108.json`, the paired GA set recomputes to n=11, mean +6.807240 meV, sd 47.353657 meV; Sr recomputes to n=12, mean -4.310502 meV, sd 59.609485 meV. These agree with the published one-decimal statistics.
- In the isolated clone, `python3 scripts/20_test_checks.py` exited 0 and emitted 38 numbered groups.

### Atomic claims checked

| claim_id | assertion | evidence / independent recomputation | status |
|---|---|---|---|
| C-001 | Q1 GA/Sr paired headline statistics | raw rows + admission ledger, independently recomputed | VERIFIED |
| C-002 | q0_final formally converged | QE convergence block, the NEB gate, and canonical index | VERIFIED, but contradicted by one current authority statement below |
| C-003 | Q3 raw custody and core P2/ELAS/POL figures are reproducible | committed gzip outputs + `derive_q3.py` in isolated clone | VERIFIED for the values the script actually parses |
| C-004 | Every Q3 authority carries its NOT CITABLE demotion | canonical index and all authority documents it names | BLOCKED |
| C-005 | All current documents agree on q0_final endpoint state | Q0 authority documents and raw QE output | BLOCKED |
| C-006 | Q3 derivation covers every claimed Q3 result | derivation source, state-metric source, raw P1/P2/projwfc records | BLOCKED |

### Blocking findings

1. [HIGH] F-006 — The committed Q3 package does not contain a reproducible transformation for all current Q3 quantities. In particular, the reported 159-shared-atom P1/P2 cosine and the alignment figures in `Q0_RESOLVED.md` / `P1_REFERENCE_AUDIT.md` are not calculated by `derive_q3.py`; it merely checks that the two projwfc files exist. The only supplied metric script explicitly skips a cosine for the 160-atom versus 159-atom vectors, and no committed shared-atom mapping/weight record supplies the missing transformation. This blocks use of Q3 as gate or publication evidence.

2. [HIGH] F-008 — The Q3 NOT CITABLE correction remains absent from two authority documents which `RESULTS_INDEX.md` itself names for Q3: `Q0_RESOLVED.md` and `P1_REFERENCE_AUDIT.md`. Both present live CBM-like/Q3 claims without a demotion marker. The existing sweep test enumerates only three documents and cannot establish repo-wide propagation.

3. [HIGH] F-011 — `Q0_POLARON_EXCLUDED.md` currently says q0_final “plateaued without converging,” while the current gate, canonical index, and raw QE output all record formal convergence. This unmarked stale assertion makes the endpoint and gate status internally inconsistent.

### Non-blocking caveats

- `C-SCOPE-001` is SKIP because the machine-readable request scope is prose rather than a path-pattern list. It is SOFT and did not determine this decision.
- No prior finding is claimed closed: the supplied fix commits for F-005/F-006/F-008/F-009 are not the audited commit, so the required fixed-commit closure condition is not met.

### Independent recomputations

- Q3 custody/core derivation: `results/objective1/dft/charge_relaxed/q3_raw/INPUT_MANIFEST.json` and compressed raw outputs → SHA-256 and `derive_q3.py` → all 18 manifest records match; P2/ELAS/POL outputs as stated above.
- Objective 2: `paired_raw_108.json` + `admission_108.json` → match by recorded `(member, system)` key, calculate `Ea(doped) - Ea(undoped)` and sample sd → published GA/Sr headline values.
- q0 endpoint: `q0/q0_final_ns1.out.gz` → QE's final convergence block → 9.8E-05 Ry energy error, 1.6E-03 Ry/Bohr gradient error, 10 BFGS steps.

### Recommendation to Claude Science

- Preserve the raw Q3 files, then commit an explicit P1-to-defective shared-atom mapping, derived per-atom weights, and a script that recomputes the cosine and aligned-energy quantities; make its failure fixture remove or corrupt that mapping.
- Apply the Q3 NOT CITABLE marker to every authority named by the Q3 index row until a valid re-audit closes it, and make the sweep discover authorities from the index instead of a hand-maintained subset.
- Remove or explicitly mark the stale q0_final plateau assertion, then extend the semantic authority sweep to reject it.

### Forbidden until closure

- Submit the q=0 production CI-NEB job on the basis of the presently inconsistent gate record.
- Publish or cite Q3 polaron/shallow-donor claims as independently reproducible.

### Required next report

- Fixed commit SHA; all three finding dispositions; raw/Q3 mapping and derivation command with exit code; semantic sweep output listing every Q3 authority discovered from `RESULTS_INDEX.md`; and a clean-clone test transcript.

### Execution declaration

- Codex repository changes: NONE to the Science Repo.
- Codex remote/HPC/GPU/instrument actions: NONE.
- Audit artifacts were written only under this cycle directory.
