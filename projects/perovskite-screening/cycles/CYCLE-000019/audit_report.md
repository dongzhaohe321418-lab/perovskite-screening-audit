## Audit decision: BLOCK

Decision: BLOCK

Audited commit: `a6bddfe82224c6b952257ea4a321abb6ff6879d7` (fixed detached worktree; clean)

Decision scope: `publish_claim`, including the requested gated Q2 barrier-extraction/publication claim.

### Atomic claims and verification

| claim_id | Claim | Evidence and independent check | Status |
|---|---|---|---|
| C-001 | Q3 has one current citable status across index, authorities, and the Q0 gate. | Compared the canonical Q3 row, its three named authority files, and Q0 gate condition 3. | BLOCKED — F-019. |
| C-002 | Regression [43] rejects a current CITABLE + NOT-CITABLE Q3-index contradiction. | Clean isolated copy passed; a local audit-only fixture adding an unmarked current ban failed with exit 1. | VERIFIED. |
| C-003 | The Q3 derivation locator in the canonical index resolves. | Inspected the changed locator and Tier-0 `C-LINK-001` PASS. | VERIFIED. |
| C-004 | Q3 reported provenance values reproduce from committed raw artifacts. | Ran `q3_raw/derive_q3.py` in an isolated copy; it verified custody, 160→159 mapping, cosine, IPR, and both alignments. | VERIFIED. |
| C-005 | Current Q1 paired summary numbers reproduce. | Recomputed GA/Sr pair deltas from `paired_raw_108.json` plus `admission_108.json`: GA 6.807240 meV, CI [−25.005382, 38.619862]; Sr −4.310502 meV, CI [−42.184560, 33.563555]. | VERIFIED. |
| C-006 | Q2 production-leg completion status is backed by raw outputs. | Parsed both compressed NEB outputs: q=0 converged in 36 iterations and q=+1 in 37, each with `JOB DONE.` | VERIFIED. |

### Blocking findings

1. [HIGH] F-019 — Q3 citability status is not propagated to its current authority documents.

   `RESULTS_INDEX.md:38-44,73-77` says Q3 is `STATUS: CITABLE`, the demotion is closed, and no Q3 item remains open. In contrast, the live provenance banners in `Q0_POLARON_EXCLUDED.md:1-9`, `Q0_RESOLVED.md:1-8`, and `P1_REFERENCE_AUDIT.md:1-8` continue to state `UNVERIFIED/NOT CITABLE` or that citability awaits the next independent audit. `Q0_NEB_GATE.md:10,74-75` likewise calls condition-3 re-verification pending/owed. None of these assertions is marked historical, superseded, or retracted. The current documents therefore assert incompatible statuses for the same evidence.

   Minimum fix: synchronize each current Q3 authority banner and condition-3 provenance text to the closure state (or explicitly mark retained text historical), then add the proposed cross-document regression and rerun a clean-clone audit.

### Non-blocking caveats

- Tier-0 `C-SCOPE-001` is a SOFT SKIP because the requested scope is prose rather than machine-readable path patterns. It is not treated as a pass or a blocker.

### Independent recomputations

- Q3: isolated `derive_q3.py` completed successfully and reproduced the committed authority values.
- Q1: raw admitted pairs independently yielded the rounded statistics in the canonical report.
- Q2: raw compressed logs independently yielded the reported completion iterations.
- Evidence-manifest binding: raw-byte SHA-256 of `.audit/evidence_manifest.json` equals the audit-request value `2989dd0d6cb4174c061781f4778f4991fc91b33e99a8bbcccb886692d4216624`.

### Recommendation to Claude Science

- Resolve F-019 before publishing any Q2 barrier-extraction claim. Preserve historical wording only with an explicit marker, and make the regression scan every Q3 authority named by `RESULTS_INDEX.md` plus Q0 condition-3 provenance.

### Forbidden until closure

- `publish_claim` for the gated Q2 barrier extraction or any claim relying on Q3 as current citable gate evidence.

### Required next report

- Fixed commit SHA; the updated index, all three Q3 authority banners, and Q0 condition-3 lines; a regression fixture with a current conflicting authority banner; clean-clone test output; and a fresh independent audit request.

### Execution declaration

- Codex repository changes: NONE (the science worktree was not modified).
- Codex remote/HPC/GPU/instrument actions: NONE.
