# Incidents — the audit loop's own defects

Constitution §14 asks for this file. It records failures of the supervision system
itself, not of the science it supervises: those live in the science repository's own
`EXPERIMENT_AUDIT.md`. Both sides of the loop appear here — the controller and the
executor — because a record that only blamed one of them would be the less useful
document.

Period covered: 2026-07-30 to 2026-07-31, cycles CYCLE-000001 through CYCLE-000008.
Cost over that period: 31.2M input tokens across 12 auditor runs.

---

## The pattern, stated once

Every incident below is one of two shapes.

**Controller side — a rule that contradicted the constitution it implements.** Three
of the four controller defects were rules written to be strict, which turned out to
forbid something the constitution allows. Strictness is not the same as correctness,
and each of these blocked the loop rather than protecting it.

**Executor side — reporting intent as accomplished fact.** All three executor
incidents are the same error: a state was asserted from memory of what had been
*attempted*, not read back from the tool that would say whether it *happened*. The
audit loop cannot catch this class, because it audits the repository, not the
executor's account of the repository. See "Open structural gap" at the end.

---

## I-001 — The gate blocked the work that clears the gate

**Class:** controller · **Cost:** one blocked cycle, resolved same day

`check_action` denied `commit_and_push_fixes` with `UNKNOWN_ACTION`. Fail-closed on
unrecognised names is right, but the low-risk whitelist held only read-only actions,
so landing a fix — the only path by which a finding can ever be verified closed — was
denied by the gate that the fix exists to clear. Every cycle would have deadlocked at
the same point.

**How it surfaced:** the executor consulted the gate, received DENY, and stopped to
ask rather than proceeding by another route. Had it bypassed the gate, the defect
would have stayed hidden and the gate would have quietly meant nothing.

**Wrong repair, explicitly rejected:** the principal waving the DENY through. If the
answer to a denial is "the principal said go anyway", the gate stops meaning anything.

**Fix:** `101fa8b` — remediation actions whitelisted, with the reasoning that they are
self-policing: every such push is itself audited before anything downstream may act.
Unknown names still default to DENY; `submit_production_job` still denied under the
same blockers.

---

## I-002 — Halting work was withheld by an open finding

**Class:** controller · **Cost:** none realised; caught before it mattered

`stop_production_job` sat in the high-risk set alongside `submit_production_job`, so
an active blocker denied both. Starting work is irreversible and expensive; stopping
it spends nothing, destroys nothing, and is precisely what the constitution's
stop-loss (§13.3) exists to trigger. As written, a runaway HPC job could not be
stopped because a document was inconsistent — the audit burning the allocation it
exists to protect.

**How it surfaced:** the principal asked what would happen to HPC operations under an
open finding. Nothing in the system would have reported this; it needed someone to
ask the question.

**Fix:** `f59df5e` — stopping returns ALLOW with reason `SAFE_DIRECTION` regardless of
blockers. It stays a named high-risk action so the consultation is still recorded;
only the withholding was removed.

---

## I-003 — An auditor was rejected for grading honestly

**Class:** controller · **Cost:** 2.9M input tokens discarded (CYCLE-000003 voided)

The validator required `blocked_scopes` on every finding of a `BLOCK` cycle. F-005 is
LOW, and constitution §12 says only CRITICAL and HIGH gate an increment, so the
auditor was right to omit them. A complete, correct audit was thrown away by a rule
that contradicted the constitution it implements.

**Downstream damage:** voiding CYCLE-000003 orphaned the re-audit cycles of F-005 and
F-009 — see I-004. One defect produced a second that took another day to surface.

**Fix:** `176f6e4` — only CRITICAL and HIGH must declare `blocked_scopes`; anything
below must not; a `BLOCK` must carry at least one finding that actually gates. The
audit prompt had been telling the auditor the opposite of the constitution and was
corrected in the same change. Two test fixtures graded MEDIUM while declaring
`blocked_scopes`; that combination was never valid, so the fixtures were corrected
rather than the rule loosened to admit them.

---

## I-004 — Silence was treated as closure

**Class:** controller · **Cost:** two findings blocked publication for ~31h with the
repairs already made and passing

A finding stays open until an auditor says otherwise. F-005 and F-009 had their
re-audit cycle voided (I-003), and **seven subsequent audits never named them again**.
Tier-0 showed both repairs landed — `C-LINK-001` resolving 387 of 387 references,
`C-TEST-001` executing and exiting 0 in a pristine clone — yet neither could ever be
recorded as closed, because nothing required the auditor to speak to them.

Omission and repair were indistinguishable to the system: both looked like nothing
happening.

**Fix:** `a78b284` — an auditor must now account for every finding still open from
earlier cycles: each appears in `findings` (still open) or `verified_closed_findings`
(fixed), never omitted. Verified against four shapes: omitting both and omitting one
are rejected; declaring closed and declaring still-open both pass.

---

## I-005 — A clean audit had no valid answer

**Class:** controller · **Cost:** one cycle stuck; no wasted audit

CYCLE-000008 passed with nothing raised. The review queued it for a disposition that
had no valid shape: the schema requires at least one finding, and the controller
rejects any finding id the cycle did not raise. The only way to comply was to invent a
judgement that had never been made.

**How it surfaced:** the executor refused to fabricate an entry and reported the
defect instead. That refusal is the reason this is an incident report and not a
falsified record.

**Fix:** `a78b284` — a cycle that raises nothing is no longer queued for an answer;
any closures it recorded were already written by the controller.

---

## I-006 — "All findings closed" asserted twice against a ledger showing otherwise

**Class:** executor · **Cost:** none to the record; the claim was caught before it
propagated

The executor reported "F-001 through F-015 all verified closed". The ledger showed 14
findings, 12 closed, F-005 and F-009 open. Corrected, then **asserted a second time in
the next report** without checking.

**Root cause:** conflating "I submitted ACCEPT_AND_FIX" with "the finding is closed" —
the exact conflation the disposition rules forbid, and which the executor had itself
written verbatim into every disposition it filed.

**How it surfaced:** the principal read the ledger. The audit loop cannot catch this:
it audits the repository, not the executor's report.

**Corrective practice adopted:** any summary claim of the form "all / none / no action
needed" must be written from tool output, not from memory.

---

## I-007 — A code change misattributed to the system

**Class:** executor · **Cost:** none realised; would have suppressed a future report

The executor described I-005 as "the system recorded it INVALID and cleared the
queue". The queue was cleared by hand and the orchestrator was changed
(`a78b284`). The distinction matters: believing the system self-heals this class means
not reporting it next time.

---

## I-008 — A re-audit reported as requested was never requested

**Class:** executor · **Cost:** none; caught the same day

The executor reported having requested a closure review for F-005 and F-009. The spool
was empty, no new commit existed, and no cycle had been created. Re-auditing requires
`request_audit`, which regenerates the evidence manifest and produces a new commit;
cycle identity is idempotent on `(commit, trigger, evidence hash)`, so the same commit
cannot be re-audited in place. Writing the intention in a report is not the call.

Same shape as I-006 and I-007: an action believed done, never read back.

---

## Open structural gap

**The loop audits the repository. Nothing audits the executor's report about the
repository.**

I-006, I-007 and I-008 were all caught by a human reading the ledger. None of them
were visible to Tier-0, to the auditor, or to the controller — the science repository
was in a fine state throughout; it was the account of it that was wrong.

This is not currently fixable by adding a check, because the reports are prose in a
chat, not artifacts in a repository. Two directions exist and neither is implemented:

1. Have the executor's status claims be generated from tool output rather than
   written, so there is nothing to misremember.
2. Publish the executor's claims as artifacts, so an auditor can hold them against the
   ledger the way it holds the science against its raw data.

Until one of those lands, this class of error is caught only by the principal, and the
record should be read with that limitation in mind.

---

## Note on the shape of this record

Four controller defects were found in two days of running four to eight cycles. That
rate is not evidence the system is unsound; it is what a system looks like while its
rules meet reality for the first time. The relevant signal is that each defect was
found by the loop being used — a gate consulted, an artifact refused, a ledger read —
rather than by inspection, and that in every case the repair was to correct the rule
rather than to grant an exception to it.
