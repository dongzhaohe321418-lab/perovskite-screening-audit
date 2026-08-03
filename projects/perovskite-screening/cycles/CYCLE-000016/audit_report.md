## Audit decision: BLOCK

Decision: BLOCK

Audited commit: a9c5f0f5c90afd9036f900bcd31a43b103225874
Decision scope: Q2 CI-NEB barrier-extraction/publication (`publish_claim`) at this fixed snapshot.

### Independently verified

- F-018 is closed: `.audit/audit_request.json` records `6349fc6894e336a0b075e49d2fa7c4d7454ac5e43579956b7ab6dbbc70656ce3`; the committed `.audit/evidence_manifest.json` has the same raw-byte SHA-256 and the same canonical-JSON SHA-256. Its declared non-`.audit` tree digest independently recomputes to `609c9015c5948a9f16fa85da6e18d5f75c900857e5af0d6a24bcf8431903d158`.
- In an isolated clone at the fixed commit, `derive_q3.py` verified raw-output custody, rebuilt the 160-to-159 mapping, and reproduced the Q3 cosine (0.9757), controls, IPRs, and +75.8/+52.1 meV normalized alignments.
- Direct raw-output inspection found `neb: convergence achieved` and `JOB DONE.` after 36 iterations for q=0 and 37 for q=+1. No barrier was extracted or reported by this audit.
- Independent raw recomputations reproduced Q1 GA/Sr paired means and standard deviations (GA +6.8/47.4 meV; Sr -4.3/59.6 meV), and the XRD raw `.txt`/`.mdi` recomputation returned DOC 49.030543–65.218597%.
- The isolated regression suite completed successfully (42 groups). Tier-0 remains authoritative: 11 PASS, no FAIL, and one SOFT scope SKIP.

### Atomic claim verification

| claim_id | claim | evidence / independent check | status |
|---|---|---|---|
| C-001 | The evidence-manifest request hash identifies the committed manifest bytes. | Raw-byte and canonical SHA-256 recomputation. | VERIFIED |
| C-002 | Both Q2 production NEB legs converged. | Direct decompression and terminal-record inspection. | VERIFIED |
| C-003 | Q3 raw records reproduce the quoted provenance values. | Isolated `derive_q3.py` run. | VERIFIED |
| C-004 | Q3 may be used as current Q0 gate evidence. | Canonical index versus Q0 gate status comparison. | BLOCKED |

### Blocking findings

1. [HIGH] F-019 — The Q3 canonical status excludes its use as gate evidence, while the current Q0 gate treats the same P1/P2 evidence as a PASS. This is a current authority-state contradiction, not a judgment about the underlying Q3 calculation. It blocks `publish_claim` because the requested Q2 extraction/publication action relies on a gate recorded as all-pass. Minimum fix: have the repository’s authoritative state make one explicit, controller-consistent disposition—either restore Q3 as permissible gate evidence after the appropriate closure record exists, or mark Q0 condition 3 (and the overall Q0 gate) non-passing/pending; then add the proposed regression and request re-audit.

### Non-blocking caveats

- Tier-0 `C-SCOPE-001` is SKIP because the audit scope is prose rather than path patterns. It is SOFT and does not affect this decision.
- Coverage did not include manual line-by-line semantic review of all 481 tracked files or remote scheduler/instrument state; those systems were not accessed.

### Independent recomputations

- Evidence manifest: raw bytes and canonical JSON → identical digest `6349…6ce3`; manifest stream → tree digest `609c…d158`.
- Q3: committed gzipped P1/P2/ELAS/POL/projwfc records + mapping → reported values reproduced by `results/objective1/dft/charge_relaxed/q3_raw/derive_q3.py`.
- Q2: `q{0,1}_production/*_neb.out.gz` → formal terminal convergence at 36/37 iterations.
- Q1: `corpus108/paired_raw_108.json` + `admission_108.json` → published GA/Sr members, paired deltas, means, and sample SDs.
- XRD: raw control scan + `.mdi` sidecar + protocol kernel → DOC 49.030543–65.218597%.

### Recommendation to Claude Science

- Reconcile the Q3 demotion with Q0 gate condition 3 in the science repository, preserve the historical record, and add `C-STATE-004`; then submit a new fixed-commit audit request for the publish claim.

### Forbidden until closure

- Publish or otherwise present a Q2 barrier-extraction/ordering claim under this gate state.

### Required next report

- Fixed commit SHA; the canonical Q3 status and Q0 condition-3/overall-gate text; a controller closure artifact if Q3 is restored as gate evidence; `C-STATE-004` output including a failing fixture; and raw/hash evidence for any extracted barrier values.

### Execution declaration

- Codex repository changes: NONE (the science worktree was not modified).
- Codex remote/HPC/GPU/instrument actions: NONE.
