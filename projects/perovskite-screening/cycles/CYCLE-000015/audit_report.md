## Audit decision: BLOCK

Decision: BLOCK

Audited commit: `c6372d99c5c3250d02b0308d517de9f1dee114fd`

Decision scope: the requested gated Q2 barrier-extraction `publish_claim`. This opinion applies only to this fixed snapshot.

### Independently verified

- Tier-0 is bound to the audited commit: 11 checks PASS, with no FAIL, ERROR, or HARD SKIP. Its only SKIP is the SOFT scope-pattern check (`C-SCOPE-001`).
- The previously closed F-017 Q2-state correction remains effective. `RESULTS_INDEX.md` and `PRODUCTION_NEB_STATUS.md` state that both legs converged; the stale assertions in `CHARGE_STATE_ANCHOR.md` and `Q0_NEB_GATE.md` are explicitly superseded/historical.
- Direct decompression of the committed raw outputs found `neb: convergence achieved in 36 iterations` then `JOB DONE` for q=0, and 37 iterations then `JOB DONE` for q=+1. The committed q=0 and q=+1 digest records match the independently recomputed production artifacts checked here.
- In a clean detached clone, `python3 scripts/20_test_checks.py` exited 0 for all 42 groups. Altering the F-017 supersession banner in an isolated fixture made group 42 fail (exit 1), so the new semantic sweep has a working negative control.
- The evidence manifest's internal non-`.audit` tree digest recomputes to `609c9015c5948a9f16fa85da6e18d5f75c900857e5af0d6a24bcf8431903d158`, matching its recorded `tree_sha256`.

### Blocking findings

1. [CRITICAL] `.audit/audit_request.json:3-4` identifies `.audit/evidence_manifest.json` with SHA-256 `51d2d87450610115d4c543d2aed1cc039cd2fded9bb2fdad8a860acf71f81cc5`, but the committed file's raw-byte SHA-256 is `92f81c6a638f241529f6d906462c514a1c09bd41ae5f0bb5837f2206359ae814`. The file-level evidence reference therefore does not identify the manifest it names. Regenerate the request binding with the exact raw-byte digest, bind controller context to the same value, and re-audit the resulting commit before publishing a Q2 barrier claim.

### Non-blocking caveats

- `C-SCOPE-001` is SOFT/SKIP because the requested scope is prose rather than machine-readable path patterns. It is not treated as a pass and does not create a HARD failure.

### Independent recomputations

- Q2 execution state: decompressed both production NEB outputs and verified their terminal convergence markers; recomputed the checked q=0/q=+1 artifact digests against their committed custody records.
- F-017 correction: ran the complete repository regression suite in a clean clone and confirmed group 42 rejects an isolated removal of the supersession state marker.
- Evidence inventory: ran the manifest's documented non-`.audit` tree-hash command and compared its result with `tree_sha256`.

### Recommendation to Claude Science

- Correct the audit-request-to-evidence-manifest file hash binding, add the proposed regression check, and request a fresh audit. Do not interpret this audit as a `check_action` authorization.

### Forbidden until closure

- Do not execute or publish the Q2 barrier-extraction `publish_claim`, quote a Q2 barrier value, state a charge-state ordering, or compare the result with the Tyagi ordering.

### Required next report

- The new commit SHA; the exact raw-byte SHA-256 of `.audit/evidence_manifest.json`; the matching value in `.audit/audit_request.json` and controller context; a passing `C-AUD-001` receipt including its mismatch fixture; and the requested action authorization.

### Execution declaration

- Codex repository changes: NONE to the Science worktree.
- Codex remote/HPC/GPU/instrument actions: NONE.
