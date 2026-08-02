## Audit decision: PASS WITH CAVEATS

Decision: PASS_WITH_CAVEATS

Audited commit: `c1e973cac911cba9efcbbb6966ca5eb8d1d12302`

Decision scope: evidence custody and authority-document state for the completed q=0/q=+1 production CI-NEB pair; this is an audit opinion only and does not authorize barrier extraction, publication, or any production action.

### Independently verified

- The evidence-manifest recomputation produced `9b09c213a7418415307c27f8bd8689357fdf37a2d009198d737f2c34dd9acc73`, matching the committed manifest; the fixed worktree was clean and at the requested commit.
- The production-pair fingerprint declares no difference beyond `tot_charge`; both inputs retain `conv_thr=1e-8`, `degauss=0.005`, CI `auto`, `path_thr=0.05`, five images, Γ, PBE+D3(BJ), and `nspin=1`.
- The raw q=0 output records `neb: convergence achieved in 36 iterations` and `JOB DONE`; its decompressed output/path SHA-256 values match the q=0 custody record. The archive contains 38 snapshots, including the final duplicate of iteration 36.
- The raw q=+1 output records `neb: convergence achieved in 37 iterations` and `JOB DONE`; its compressed and decompressed SHA-256 values match `CONVERGENCE_SUMMARY_q1.json` and `SHA256.txt`. The final five errors in the raw output match the summary and are all at or below 0.05 eV/Å. The archive contains 39 snapshots, including the final duplicate of iteration 37.
- None of the four terminal production activation-energy literals found in the compressed raw outputs occurs in uncompressed tracked text. `PRODUCTION_NEB_STATUS.md` does not extract or quote a production barrier.
- An isolated detached clone at this commit ran `python3 scripts/20_test_checks.py` successfully: 41 numbered groups, exit 0.

### Atomic-claim ledger

| Claim | Evidence / independent check | Status |
|---|---|---|
| q=0 completed at iteration 36 | terminal raw `q0_neb.out.gz`; archive index and custody hash | VERIFIED |
| q=+1 completed at iteration 37 | terminal raw `q1_neb.out.gz`; parsed summary, archive index, and custody hashes | VERIFIED |
| production pair is fingerprint-locked except charge | `fingerprint_check.json` and the two committed inputs | VERIFIED |
| no production activation/barrier value was extracted into current production authority text | terminal-value literal sweep outside compressed raw outputs; `PRODUCTION_NEB_STATUS.md` | VERIFIED |
| no barrier/activation number exists anywhere in the entire tree | historical, methodology, literature, and raw-output references exist; the literal global formulation is not applicable to the production-extraction gate | NOT VERIFIED AS LITERALLY WORDED |

### Blocking findings

None. No CRITICAL or HIGH finding was identified.

### Non-blocking caveats

1. [LOW] F-016 remains open: Tier-0 C-LINK-001 found three unresolved repository-path-shaped references. This is a navigation defect only and does not block the audited production evidence.

### Independent recomputations

- Evidence tree: `git ls-files -z -- ':!.audit/**' | xargs -0 shasum -a 256 | shasum -a 256` → manifest tree SHA-256 above.
- Raw custody: decompressed q=0/q=+1 output and path files were hashed and matched their recorded custody digests; archive indexes report 38 and 39 snapshots respectively.
- Terminal status: raw outputs were parsed directly for the terminal convergence and `JOB DONE` blocks; the q=+1 final error vector was compared to `CONVERGENCE_SUMMARY_q1.json`.

### Recommendation to Claude Science

Keep F-016 open until the three document paths are corrected. The controller/Claude Science must separately decide whether the requested barrier-extraction action is permitted; this report does not perform or authorize it.

### Forbidden until closure

- Do not treat this audit as `check_action` ALLOW, PI authorization, a barrier extraction, or a publication approval.

### Required next report

- If barrier extraction is requested, provide the exact derivation script, source raw paths, input/output hashes, extracted values, and an explicit controller action record at a new fixed commit.

### Execution declaration

- Codex repository changes: NONE (science worktree unchanged).
- Codex remote/HPC/GPU/instrument actions: NONE.
