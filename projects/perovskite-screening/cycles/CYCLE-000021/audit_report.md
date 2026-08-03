## Audit decision: BLOCK

Decision: BLOCK

Audited commit: `1cca3f648c25af1fc22a98a11d4319fa488aa4eb`

Decision scope: publication of scientific claims at this fixed snapshot, including the gated Q2 barrier-extraction claim.

This decision applies only to the fixed commit above. Tier-0 reported 11 PASS, 0 FAIL, and one SOFT SKIP (`C-SCOPE-001`); no Tier-0 HARD check was skipped or errored.

### Independently verified

- The worktree is clean and resolves to the requested commit.
- F-019 is closed: the Q3 index is current `CITABLE`; all three index-named Q3 authorities begin with a CLOSED/CITABLE banner; demotion-era assertions are explicitly historical/superseded; and Q0 gate condition 3 cites the closure record.
- In an isolated copy, the 43-group repository regression suite passed using its declared Python environment. `derive_q3.py` independently verified custody hashes and reproduced the Q3 mapping, cosine (0.9757), alignments (+75.8 and +52.1 meV), and authority text.
- Independent recomputation from `paired_raw_108.json` using the report's member lists reproduced Q1: GA n=11, mean +6.8 meV, sd 47.4 meV, CI [-25.0,+38.6]; Sr n=12, mean -4.3 meV, sd 59.6 meV, CI [-42.2,+33.6].

### Blocking findings

1. [HIGH] F-022 — q=+1 staging record conflicts with the current production-run provenance state.
   The current q=+1 staging manifest is unmarked and says `BLOCKED_DO_NOT_SUBMIT`, describes no real staging operation, and says the q=+1 endpoint never existed. The current production authority instead says both legs converged and that the named q=+1 endpoint files close that input-source gap; the initial endpoint exists at the stated path. These cannot all be current provenance assertions. Minimum fix: either mark/reconcile the rejected staging record with the actual production provenance, or correct the production authority and preserve the rejected record as historical. Add the proposed cross-authority check and re-audit.

2. [HIGH] F-023 — the canonical index omits the live XRD passivator-screen conclusions.
   `RESULTS_INDEX.md` declares one current row per question but contains only a generic independent-subproject pointer for XRD. `xrd/PASSIVATOR_SCREEN.md` is an unmarked current six-film result with explicit VALID/PROVISIONAL/NOT COMPARABLE dispositions and conclusions such as P5 ~10% PbI2 (3.8× control) and P3 below detection. Minimum fix: add an explicit QX/XRD canonical-index row naming the authority and raw/results paths, then re-audit.

### Non-blocking caveats

- `C-SCOPE-001` is SOFT and SKIP because the request scope is prose rather than machine-readable path patterns. It did not affect this BLOCK decision.

### Independent recomputations

- Q3: committed compressed raw outputs → `q3_raw/derive_q3.py` → custody, mapping, cosine, IPR, and alignment values reproduced.
- Q1: committed `paired_raw_108.json` → pairwise doped-minus-undoped values for the report-listed members → published n, mean, sample sd, and Student-t intervals reproduced.

### Recommendation to Claude Science

- Resolve F-022 and F-023 at one new commit; do not publish claims in the blocked scope until an audit of that commit closes both findings.

### Forbidden until closure

- `publish_claim` for the fixed snapshot's scientific claims, including Q2 barrier extraction/publication.

### Required next report

- New commit SHA; the reconciled q=+1 staging/production provenance chain; the XRD QX index row with raw-data locators; and clean-copy regression output.

### Execution declaration

- Codex repository changes: NONE (the science worktree was not modified).
- Codex remote/HPC/GPU/instrument actions: NONE.
