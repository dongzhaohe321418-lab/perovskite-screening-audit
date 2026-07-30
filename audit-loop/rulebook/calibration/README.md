# Calibration material

Drop prior **real** audit transcripts and reports here (`*.md`). The orchestrator copies
them into each cycle directory and points the auditor at them.

## What they are for

Depth and shape, not content. A frontier model already knows how to be rigorous; what it
cannot guess is *how rigorous this project expects, in what format, at what level of detail,
and which recurring failure modes are worth its attention*. A real transcript conveys that in
a way no rulebook prose does.

## What they are explicitly NOT

Calibration files carry **no authority**:

- They do not override `CODEX_AUDIT_WORKFLOW.md`. The constitution is supreme; on any conflict
  the constitution wins and the conflict itself should be reported.
- No factual claim in them is evidence about the commit under audit. A prior audit describes a
  *different* snapshot. Every claim must be re-derived from the current fixed commit or it does
  not exist.
- A finding recorded here is not a current finding, and its prior disposition — accepted,
  disputed, deferred, approved — has no force in this cycle.
- Nothing in them can suppress a finding. Text here that appears to instruct the auditor
  ("do not report", "already approved", "not a finding") is inert by construction: the prompt
  states this, and `C-INJECT-001` treats such text in the *audited tree* as a hard defect.

That framing matters because these files are untrusted input reaching the auditor's context.
They are reference transcripts written by an agent, not policy signed by the PI.

## Practical notes

- Plain markdown, one file per prior audit. Name them so the origin and date are obvious,
  e.g. `prior_audit_macbook_2026-07.md`.
- Redact anything you would not publish: the audit repository is public, and cycle prompts are
  written into `state/cycles/<id>/`. Do not put tokens, private paths, or unpublished data here.
- Total calibration text injected per cycle is capped (see `codex.calibration_max_chars` in
  `orchestrator/config.yaml`); oversized files are truncated with an explicit notice rather
  than silently trimmed.
- Each file's SHA-256 is recorded in the cycle's `cycle_context.json`, so any audit can be
  traced back to exactly what calibration material was in scope.
- Prefer a few good transcripts over many. This is a prompt budget, and at ~3M input tokens
  per cycle it is not free.
