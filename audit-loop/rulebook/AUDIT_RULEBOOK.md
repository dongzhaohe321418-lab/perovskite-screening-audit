# AUDIT RULEBOOK — scientific process and evidence integrity

**rulebook_version:** 1.0.0

This is the normative rulebook for the automated audit of a scientific repository. It is written
for an LLM auditor (Codex) operating read-only on a fixed Science Commit, downstream of a
deterministic checker and upstream of a controller that turns findings into blocking decisions.

Every finding the auditor emits must cite a rule ID defined in this file. The auditor may not
invent rule IDs. The machine-readable enumeration of this file is `rulebook.lock.json`, produced
by `lock_rulebook.py`; authoritative rule counts live there, not in this prose.

---

## How to use this rulebook

One audit cycle:

1. The controller fixes a **Science Commit** and hands the auditor the repository at that commit,
   read-only, plus this rulebook and its lock file.
2. The auditor verifies that `rulebook.lock.json` was generated from the rulebook it just read
   (`sha256` of the raw bytes) and records `rulebook_version` in its run metadata. If the lock is
   stale, the auditor stops and reports that — auditing against an unlocked rulebook is not a
   valid cycle.
3. The **Tier-0 deterministic checker** has already run and emitted `check_report.json` with check
   IDs of the form `C-*`. The auditor reads it first. Its verdicts are machine truth
   (see *Tier-0 deference*).
4. The auditor then works **rule by rule**, in family order. For each rule it applies the rule's
   own *how to audit* procedure to the artifacts named in *applies_to*.
5. Each defect becomes one finding carrying the fields required by *Citation requirement*.
6. Every HARD finding not already reported by a Tier-0 check must also propose a new `C-*` check
   that would catch its defect class mechanically next cycle.

The auditor reads this rulebook as a checklist to be exhausted, not as inspiration. A rule that
does not apply to the commit under audit is skipped silently; a rule that applies and passes needs
no finding. Coverage claims ("all rules applied") must be truthful: if the auditor could not apply
a rule because the evidence needed to apply it is absent, that absence is itself a finding under
`R-EVD-006`.

---

## Rule 0 — Scope: process and evidence integrity, never scientific merit

**This is the precondition for every rule below. It has no `R-` ID and may not be cited in a
finding; it constrains how every other rule is read.**

The audited party owns all scientific judgment. This audit system exists to check that the record
is internally consistent, that its numbers are traceable to committed artifacts, that its status
claims match reality, and that its corrections propagate. It does **not** exist to second-guess
the science.

Permitted subjects of a finding:

- a quoted number that does not recompute from the committed artifact the document cites;
- a status claim contradicted by the artifact it cites or by another document;
- a hash, path, or reference that does not resolve;
- a correction that did not reach every document repeating the claim;
- a comparability declaration that is missing, or that the document itself then violates;
- a guard, check, or verification tool that misreports;
- a self-declared count, index, or enumeration that does not match the artifact it describes;
- a declared procedure (staging, gating, append-only logging) that was not followed.

Forbidden subjects of a finding — the auditor must never state or imply a position on:

- whether a physical result is right, plausible, or expected;
- whether a computed barrier, energy, or constant has a reasonable value;
- whether a method, functional, potential, sampling scheme, convergence threshold, statistical
  test, or significance scale was well chosen;
- whether a conclusion is scientifically sound, novel, or sufficiently supported *as science*;
- whether more or different calculations *should* have been done for scientific reasons.

The rewrite discipline: whenever a rule tempts you toward *"the auditor should assess whether X is
correct"*, the rule must instead say *"the auditor must check that X is derivable from the
committed artifact the document cites."* Every rule below carries a **not in scope** line naming
the adjacent scientific judgment it must not make. If a candidate finding cannot be expressed
without crossing one of those lines, it is not a finding.

Two consequences worth stating plainly:

- **Enforcing a declaration is not judging it.** When the repository declares that two quantities
  are incomparable, the auditor enforces that declaration as written and never evaluates whether
  the declaration is physically correct. If the repository declares them comparable, the auditor
  checks only that the declaration exists and that the document is self-consistent with it.
- **A wrong number and an untraceable number are different findings.** The auditor reports only
  the second: the number does not follow from the cited artifact. Whether the true value is
  something else is the audited party's to determine.

---

## HARD / SOFT doctrine

Every rule declares exactly one class, and that class is the rule's **maximum**.

**HARD** — a mechanically demonstrable defect. Examples of the whole category: a hash that does not
resolve; a number that does not recompute from the cited artifact; a status claim contradicted by
another artifact; a broken required reference; a missing required file; a test that fails; a
declared count that differs from the count of the thing it counts; a guard that reports a verdict
its own fixtures contradict. **Only HARD findings may block downstream action.**

**SOFT** — methodological opinion, readability, document structure, suggested additional
verification, coverage recommendations. SOFT findings are recorded and tracked. They are **never
blocking** and are **never grounds for halting work**, delaying a launch, or withholding approval.
A SOFT finding may not be escalated by aggregation: ten SOFT findings are still not a blocker.

**The test for HARD:** *could a script, given the repository at this commit, prove this?* If the
demonstration requires judgment — about quality, style, adequacy, or what would have been better —
it is SOFT. If the demonstration is an exhibit (this hash, that line, these two numbers), it is
HARD.

Class rules that follow from the doctrine:

- A finding's `finding_class` may not exceed the class its rule declares. A HARD rule may produce
  a SOFT finding when only the weaker, judgment-shaped part of the invariant is at issue (each
  such downgrade is noted in the rule's text). A SOFT rule can never produce a HARD finding.
- A SOFT rule must declare `deterministic_check: none`. If a script can decide it, the rule
  belongs in HARD. `lock_rulebook.py` enforces this structurally.
- A HARD finding must be reproducible at the fixed audited commit by the command it carries. If
  the auditor cannot write that command, the finding is not HARD.

---

## Citation requirement

Every finding must carry:

| field | requirement |
|---|---|
| `rule_id` | A rule ID defined in this rulebook, exactly as written, `^R-[A-Z]{3}-[0-9]{3}$`. Inventing an ID, or citing a family prefix that does not exist here, invalidates the finding. |
| `finding_class` | `HARD` or `SOFT`, and never greater than the cited rule's declared class. |
| `source` | `DETERMINISTIC` when the finding merely reports the result of a Tier-0 check; `JUDGMENT` when the auditor derived it by its own work. |
| `check_id` | Required when `source` is `DETERMINISTIC`: the `C-*` ID from `check_report.json` being reported. Forbidden when `source` is `JUDGMENT` — a judgment finding may *propose* a check but may not claim one ran. |
| `reproduce` | Required for every HARD finding: one command, runnable against a clean clone at the audited commit, whose output demonstrates the defect. |
| `evidence` | Whatever the rule's *evidence required* line demands. A finding missing it is not actionable and must not be emitted. |
| `proposed_check` | Required for every HARD finding whose `source` is `JUDGMENT` (see *Tier-0 deference*). |

A finding that cites more than one rule must be split. One defect, one rule, one exhibit. If a
single artifact violates three rules, that is three findings.

Two prohibitions:

- The auditor may not create a rule ID for a defect it believes real but unlisted. It reports the
  defect under the closest existing rule and says so in the evidence, or — if no rule covers it —
  emits a SOFT finding under the family's closest rule proposing a rulebook amendment.
- The auditor may not restate the same defect under a second rule to raise its apparent severity.

---

## Tier-0 deference

A companion deterministic checker runs **before** the auditor and emits `check_report.json`.
Its entries are identified by check IDs of the form `C-*` and carry PASS / FAIL / SKIP / ERROR.

The rules of deference:

1. **Tier-0 results are authoritative machine truth.** The auditor must not contradict a Tier-0
   PASS or a Tier-0 FAIL. It may not argue that a passing check should have failed, nor that a
   failing check is a false alarm.
2. **A Tier-0 failure is reported by citing it.** When the auditor reports a defect a Tier-0 check
   already caught, the finding carries `source: DETERMINISTIC` and the `check_id`. It adds context,
   never a competing verdict.
3. **The one exception is tooling integrity, and it is not a contradiction.** If the auditor
   believes a check's *implementation* cannot decide what it claims to decide, that is a finding
   under `R-GRD-001` or `R-GRD-002` about the check itself — an exhibit that the tool's fixtures
   or logic do not cover its stated condition. It is never a re-verdict on the subject.
4. **A Tier-0 `SKIP` or `ERROR` is not a PASS.** It is an absence of information, and the auditor
   must treat the underlying rule as unaudited-by-script and audit it itself.
5. **The auditor's own work is to find what the scripts cannot** — paraphrase, cross-document
   contradiction, silent scope reduction, an assertion that matches no measurement, a correction
   that stopped one file short. Re-deriving what Tier-0 already decided is wasted cycle.

**The ratchet (converse duty).** When the auditor finds a HARD defect that no Tier-0 check caught,
the finding must propose a new `C-*` check: a proposed ID, the condition it decides, the artifacts
it reads, and the fixture that would make it fail on this very defect. The class of defect must
become mechanically detectable in the next cycle.

**Why this exists.** Two language models reviewing each other share priors, and a blind spot common
to both is invisible to any amount of further LLM review — the second model does not merely miss
the defect, it agrees with the first that nothing is there. Deterministic checks are the only part
of this system that cannot be talked out of a verdict, so the system is designed to convert
judgment into script: every defect found by reading once becomes a check that fires forever after.
Deference stops the auditor from eroding that floor; the ratchet keeps raising it.

---

## Rule families

| prefix | family | covers |
|---|---|---|
| `R-EVD-*` | Evidence resolvability | hashes resolve, referenced paths exist, quoted numbers recompute from committed raw data, results ship the inputs needed to recompute them |
| `R-STA-*` | Status truthfulness | execution status backed by preflight and output, status agreement across documents, no asserted event without a trace |
| `R-COR-*` | Correction propagation | repo-wide sweeps including paraphrase, superseded records preserved, derived numbers recomputed, the fix itself verified |
| `R-CMP-*` | Comparability declarations | a comparison states its basis and is self-consistent with it; populations and pooling attributes declared |
| `R-GRD-*` | Guard and tooling integrity | a guard's verdict tracks its condition, tool failure is not subject failure, a literal-string pin does not preserve stale text |
| `R-NAV-*` | Navigation and canonical-index integrity | the canonical index carries every current conclusion, authoritative pointers stay fresh, self-declared counts match |
| `R-PRO-*` | Procedure adherence | two-step staging, per-condition gate evidence, append-only trails, no empty substantive commits |

Rule IDs are stable. A retired rule's ID is never reused (see *Amending this rulebook*).

The field block below is the required shape of every rule section. The placeholder ID is
deliberately invalid: `lock_rulebook.py` skips fenced blocks, and if that skipping ever breaks the
locker will fail loudly on an unknown family rather than silently duplicate a real rule.

```text
### R-FAM-000 — <short imperative title>
- **class:** HARD
- **deterministic_check:** C-HASH-001        (or `none`)
- **applies_to:** <what artifacts>
- **invariant:** <one sentence, testable, stated as what must be true>
- **how to audit:** <concrete procedure the auditor follows>
- **evidence required:** <what the finding must contain to be actionable>
- **not in scope:** <the adjacent scientific judgment this rule must not make>
```

---

# R-EVD — Evidence resolvability

### R-EVD-001 — Every cited hash resolves to a committed artifact
- **class:** HARD
- **deterministic_check:** C-HASH-001
- **applies_to:** every document, manifest, staging record, launch record, and commit message that quotes a content hash (sha256, git object, checksum) as evidence of identity.
- **invariant:** Every hash quoted as evidence resolves, at the audited commit, to an artifact whose recomputed digest equals the quoted value.
- **how to audit:** Collect every hash-shaped literal quoted as evidence together with the artifact it is claimed to identify. For each, recompute the digest of that artifact at the audited commit and compare, full-length. Treat a truncated hash as resolving only if exactly one committed artifact matches the prefix; more than one match, or none, is a failure. A hash whose artifact is not committed at all is `R-EVD-006`, not this rule. Precedent: `EXPERIMENT_AUDIT.md` §1.9, where PI approval, staging, remote verification, and the launch record are all bound together by input digests — if those digests do not resolve, nothing downstream of them is checkable.
- **evidence required:** the quoting file and line, the quoted hash, the artifact path it claims to identify, and the recomputed digest (or a statement that no committed artifact matches).
- **not in scope:** whether the hashed input was the scientifically appropriate one to run, and whether its contents describe a sensible calculation.

### R-EVD-002 — Every referenced locator exists at the audited commit
- **class:** HARD
- **deterministic_check:** C-PATH-001
- **applies_to:** every file path, directory, archive member, script name, job-output reference, and intra-repository document anchor (section number, heading, table row reference) cited by any tracked document.
- **invariant:** Every locator a document cites as evidence or as navigation resolves to something that exists at the audited commit.
- **how to audit:** Extract locators from all tracked text: filesystem paths, links, archive members named inside a cited tarball, and internal references of the form used by the repository's own documents (for example a cross-reference to a numbered section). Resolve each against the commit tree, and resolve internal references against the target document's actual headings. A reference to a section number that does not exist is a failure of this rule even when the surrounding prose is otherwise sound — the repository's own audit record contains an instance of exactly this, a cross-reference to a retraction-log entry that was never written.
- **evidence required:** the citing file and line, the locator as written, and the resolution result (absent path, or absent anchor with the list of anchors that do exist in the target).
- **not in scope:** whether the referenced artifact contains the right science, and whether a different artifact would have been a better reference.

### R-EVD-003 — Every quoted number recomputes from the one artifact it cites
- **class:** HARD
- **deterministic_check:** C-NUM-001
- **applies_to:** every numeric value presented as a result, statistic, gate outcome, threshold comparison, count, or derived quantity in any current document.
- **invariant:** Every quoted number is reproducible, to the precision at which it is quoted, from the committed artifact the document names, and that artifact is uniquely identified.
- **how to audit:** For each quoted number, identify the artifact the document names as its source and recompute the value from that artifact's committed contents using the documented procedure. Report a mismatch beyond the quoted precision. Report separately the case where the citation names a *class* of artifact rather than one artifact — for example a reference band that exists in several variants — because a number that could have come from either of two artifacts is not traceable to one; the repository's own log records a retraction of exactly that shape, where a single quoted reference barrier turned out to correspond to two different committed bands with different values. Where recomputation requires a tool the auditor cannot run, do not guess: emit `R-EVD-006` instead.
- **evidence required:** the quoting file and line, the number as quoted, the cited artifact, the recomputed value with the exact recomputation command, and the discrepancy.
- **not in scope:** whether the recomputed value is physically plausible, whether the quantity is the right one to report, and whether the precision quoted is scientifically meaningful.

### R-EVD-004 — An asserted property traces to a measurement recorded in the artifact
- **class:** HARD
- **deterministic_check:** C-FIELD-001
- **applies_to:** every claim that an artifact, run, member, or path has a property — a gate outcome, a convergence flag, a parameter value, a tolerance actually achieved, a perturbation amplitude actually applied, a uniformity statement across a set.
- **invariant:** Every asserted property is backed by a value that was measured and recorded in the artifact, not by a value the document, the writer, or the generating script supplied as a constant.
- **how to audit:** For each asserted property, locate the recorded field in the artifact and compare. Two failure shapes, both HARD. First, direct contradiction: the document says an item passed every gate while the item's own recorded field says the gate failed — the repository's log records this for two named outlier configurations whose `gate_endpoints.passed` field read false. Second, and harder to see, assertion-by-construction: the property is written into every row as a hardcoded literal and never measured, so an integrity check over those rows asserts something the file never checked; the repository's log records this for a relaxation-depth target written as a constant on every manifest row. For each such field, establish whether the value has a measured provenance (a parse of a real output, a recomputation, a recorded measurement) or was supplied. Also compare a stated procedure parameter against what the artifact shows was applied — a stated perturbation amplitude that the recorded displacements contradict is this rule.
- **evidence required:** the asserting file and line, the artifact and field name, the recorded value, and — for the assertion-by-construction shape — the line of the generating script that supplies the constant.
- **not in scope:** whether the property's value is scientifically acceptable, whether the tolerance chosen was appropriate, and whether a failing item should have been included or excluded on scientific grounds.

### R-EVD-005 — Identities are joined by recorded key, never by inference
- **class:** HARD
- **deterministic_check:** C-JOIN-001
- **applies_to:** any script or documented procedure that assembles a table, ledger, manifest, or statistic by associating records from more than one source.
- **invariant:** Every association between records from different sources is made through a key both sources record, never through positional index, ordering assumption, or arithmetic on identifiers.
- **how to audit:** Read the code and the recorded provenance for every assembled table. Flag any association that relies on list position, sort order, or arithmetic of the form *identifier index plus an offset equals source index*. The repository's log records the canonical instance: an energy ledger built by assuming member index equalled seed offset, when the mapping record in the repository said otherwise, which misassigned energies for eight members and corrupted a downstream gate. Then verify the corrected form: energies matched by filename against the record that already held them, with at least one spot-check recomputed from the source artifact. Where a join key exists in both sources but the code ignores it, that is this rule even if the current data happens to align — an accidental alignment is not a join.
- **evidence required:** the script and line performing the inferred join, the record that holds the true key, and at least one concrete pair of items whose association is wrong or unverifiable under the inference.
- **not in scope:** whether the joined values are physically reasonable, and whether the quantities being assembled are the right ones to assemble.

### R-EVD-006 — A reported result commits the inputs needed to recompute it
- **class:** HARD
- **deterministic_check:** C-RECOMP-001
- **applies_to:** every document presenting a current result, statistic, gate outcome, or figure.
- **invariant:** For every current result, the artifacts required to recompute it — raw rows, parsed outputs, manifests, per-item records, and the code that transforms them — exist at the audited commit.
- **how to audit:** For each current result, enumerate what recomputation needs and check each exists in the tree: the raw record behind each statistic, the parsed convergence or output summary behind each claimed run outcome, the per-member ledger behind each aggregate, and the analysis script named as producing it. A result whose raw evidence is present only on a remote machine, only in an untracked directory, or only as a number transcribed into prose fails this rule. Report the specific missing input, not a general complaint. This rule is also the correct destination whenever the auditor cannot apply another rule for want of evidence: absence of the artifact needed to check a claim is itself the finding, and it maps to the controller's `NOT_VERIFIABLE` disposition rather than to a claim that the result is wrong.
- **evidence required:** the result and its location, the enumerated inputs recomputation requires, and which of them are absent at the audited commit.
- **not in scope:** whether the committed evidence is scientifically sufficient to support the conclusion, and whether additional calculations would strengthen it.

### R-EVD-007 — A derived constant cites the record of its inputs' residual
- **class:** HARD
- **deterministic_check:** none
- **applies_to:** any constant, coefficient, critical value, depth, or precision claim derived from a quantity whose own residual, spread, or convergence error is recorded somewhere in the repository.
- **invariant:** Every derived constant cites the committed record of its input's residual or spread, and the precision the document claims for the constant is arithmetically consistent with that record.
- **how to audit:** For each derived constant, find the citation to the record of its input's residual, spread across sampling windows, or convergence error. Two HARD findings are available and only these two. First, no such record is cited and none exists in the repository. Second, the document's own numbers are mutually inconsistent: the cited record states a residual and the document quotes the derived constant to a precision finer than that same record supports, on the document's own arithmetic. The repository's log records the instance this generalizes — coupling constants and a well depth quoted to three decimals of a millielectronvolt while the underlying localisation gain carried a recorded residual an order of magnitude larger and swung by more than twice its own value between two sampling windows. Additionally check any accompanying insensitivity claim ("the conclusion does not depend on the amplitude chosen") for a cited sweep artifact; an insensitivity claim with no sweep committed is `R-EVD-006`. This rule compares two recorded numbers against each other and nothing more.
- **evidence required:** the constant as quoted with its location, the cited residual record or a statement that none exists, and the arithmetic showing the claimed precision exceeds what the cited record states.
- **not in scope:** whether the residual is physically acceptable, whether tighter convergence is warranted, whether the constant's value is right, and whether the underlying physical effect exists — all of which belong entirely to the audited party.

---

# R-STA — Status truthfulness

### R-STA-001 — "Running" requires a recorded preflight pass and real output
- **class:** HARD
- **deterministic_check:** C-STATUS-001
- **applies_to:** every statement that a job, track, run, sweep, or test is running, in progress, or underway — in documents, status tables, commit messages, and progress notes.
- **invariant:** A task is described as running only where a preflight result for that task reports success and output produced by that task exists.
- **how to audit:** For each running-claim, locate two artifacts: the recorded preflight or submission-validation result for that exact task, and output attributable to it. Job submission is not evidence of execution and a queue identifier is not output. A task recorded as queued, pending, or awaiting resources is not running, and a document describing it as running is a HARD finding even when the submission is genuine. The repository's log names its own instance as the most serious entry in that log — twenty-four paths described as running while the job had failed five consecutive times and nothing was computing — and the standing rule adopted in response is the invariant above.
- **evidence required:** the claiming file and line, the task identifier, the preflight artifact (or its absence), and the output artifact (or its absence), each at the audited commit.
- **not in scope:** whether the task should be running, whether its resource allocation is sensible, and why it failed.

### R-STA-002 — Status agrees across every document asserting it
- **class:** HARD
- **deterministic_check:** C-STATUS-002
- **applies_to:** launch status, gate status, completion status, approval status, and per-track execution state, wherever asserted — README, canonical index, per-objective status documents, audit record, gate documents.
- **invariant:** For every task or gate, all documents asserting its status assert the same status at the audited commit.
- **how to audit:** Build the set of assertions per task or gate across all tracked documents, including headings and summary tables, then compare. Any disagreement is HARD, and the finding names every location rather than picking a winner — deciding which is correct is the audited party's job. Watch three shapes seen in this repository's own history: a section heading that says a launch awaits approval while the record inside the same section states the launch happened; an execution-state table that describes everything other than a listed set as idle while another section records a running job absent from that table; and a canonical index whose next-step field describes a gate as awaiting something the gate document records as already closed.
- **evidence required:** the task or gate identifier and, for each asserting location, the file, line, and status as written.
- **not in scope:** which status is correct, whether the task should have been launched, and whether the gate's conditions were adequate.

### R-STA-003 — No artifact asserts an event that left no trace
- **class:** HARD
- **deterministic_check:** C-TRACE-001
- **applies_to:** every assertion that a discrete event occurred — a submission, an approval, a launch, a gate closure, a sweep, a test run, a verification, a review.
- **invariant:** Every asserted event has, at the audited commit, at least one committed artifact whose existence or content is a consequence of that event.
- **how to audit:** For each asserted event, name the trace it must have left and check for it: an approval leaves a recorded approval bound to the exact scope approved; a launch leaves a launch record with identifiers and verified input digests; a sweep leaves the sweep's output or log; a verification leaves the verification's result. An assertion whose only support is another assertion of the same event is unsupported no matter how many documents repeat it. Distinguish this rule from `R-STA-001`: that rule governs the specific vocabulary of execution state, this one governs any claimed event.
- **evidence required:** the asserting file and line, the event as asserted, the trace artifact the event would necessarily produce, and confirmation of its absence.
- **not in scope:** whether the event was authorised, wise, or scientifically necessary, and whether the approver should have approved.

---

# R-COR — Correction propagation

### R-COR-001 — A retraction sweeps repo-wide, paraphrase included
- **class:** HARD
- **deterministic_check:** C-SWEEP-001
- **applies_to:** every retraction or correction recorded anywhere in the repository, and all tracked text.
- **invariant:** After a retraction, no current document asserts the retracted claim — in its original words or in paraphrase — except where explicitly marked as the superseded record.
- **how to audit:** For each entry in the retraction log, extract the claim's semantic content rather than its wording, then sweep all tracked text for restatements. Classify every hit as (a) the retracted claim restated as current, (b) a legitimate unrelated use of similar words, or (c) a properly marked historical or superseded record. Only (a) is a finding. Abstracts, summaries, headings, index rows, and figure captions are the highest-yield locations and must be swept explicitly: the repository's log records a case where the body carried the retraction while the abstract restated the retracted conclusion in different words, and the verification had matched literal strings only. Where a live inconsistency exists between a merged or corrected result and an older section still stating the pre-correction status of the same question, that is this rule.
- **evidence required:** the retraction entry, the file and line still asserting the claim, the quoted text, and a short statement of why it is the same claim rather than an unrelated use.
- **not in scope:** whether the retraction was warranted, whether the replacement claim is correct, and how strongly the corrected claim should now be worded.

### R-COR-002 — The superseded record is preserved and marked, never overwritten
- **class:** HARD
- **deterministic_check:** C-SUPER-001
- **applies_to:** every document, result, or record that a correction supersedes, and the git history of those paths.
- **invariant:** A correction creates a new canonical record or adds a superseding marker; the superseded record still exists at the audited commit, names the specific error, and its evidence was not rewritten in place.
- **how to audit:** For each correction, inspect the history of the affected paths. The superseded document must still exist, must carry a banner identifying it as superseded and naming the specific error rather than gesturing at one, and must not have had its claim text silently replaced by the corrected claim. Removal of a superseded record, or an in-place rewrite that leaves no trace of what was claimed before, is HARD. A banner that says only "outdated" without naming the error is a SOFT finding under this rule.
- **evidence required:** the superseded path, the correction commit, and either the deletion or the in-place rewrite shown as a diff, or the banner text shown to name no specific error.
- **not in scope:** whether the original claim was scientifically defensible when made, and whether the superseding document's science is better.

### R-COR-003 — Numbers derived from corrected inputs are recomputed, not carried across
- **class:** HARD
- **deterministic_check:** C-DERIVE-001
- **applies_to:** every statistic, aggregate, gate outcome, classification, and figure downstream of an input that a correction changed.
- **invariant:** Every downstream number presented as current was recomputed from post-correction inputs, and no pre-correction value survives as a current number.
- **how to audit:** Identify the correction and the inputs it changed, then enumerate everything downstream of them. For each, establish that the current value was produced after the correction — by a recorded regeneration, a provenance field, an input digest matching post-correction inputs, or direct recomputation. A reclassification that carries its pre-correction counts forward is the canonical instance and the repository's log records one that understated a mislabelling by an order of magnitude while presenting itself as the corrected picture. Where a correction changed a population's contents, check the population's own count and every statistic over it, not merely the headline result.
- **evidence required:** the correction and the inputs it changed, the downstream number still presented as current, and the demonstration that it predates the correction (provenance, digest, or recomputed value differing from the quoted one).
- **not in scope:** whether the recomputed result changes any scientific conclusion, and whether the correction's direction is physically sensible.

### R-COR-004 — A correction is verified beyond the file it fixed, and a failed correction is a new defect
- **class:** HARD
- **deterministic_check:** C-SWEEP-002
- **applies_to:** every correction and its accompanying verification — sweeps, regression checks, and re-audits.
- **invariant:** A correction is complete only when a verification whose scope exceeds the corrected file demonstrates the defect class absent repo-wide, and a correction that fails that verification is recorded as a new numbered defect entry rather than as an amendment to the original.
- **how to audit:** For each correction, read the verification it shipped and determine its scope. A sweep or regression check scoped to the single file that was edited does not verify the correction: the repository's log records a fix that reached the result document but not the self-declared canonical index, written and pushed in the same window, because both the sweep and the new regression check were scoped to one file. Then check the log's own structure: where a correction later failed, the record must contain a distinct entry for that failure, and the original entry must not have been quietly rewritten to describe the second attempt. This repository's log demonstrates the correct form — one entry records a gate corrected on a subset, and a separate later entry records that the first attempt at completing it was itself wrong and names the mechanism.
- **evidence required:** the correction, the verification and its demonstrated scope, and either the location the correction failed to reach or the missing distinct entry for a known failed correction.
- **not in scope:** whether the correction's science is right, and whether the verification method is the best available.

### R-COR-005 — Retraction entries should record how the defect was found
- **class:** SOFT
- **deterministic_check:** none
- **applies_to:** entries in the retraction and execution-failure logs.
- **invariant:** Each retraction entry records its detection route — self-review, external review, a named guard, or a named test — so that gaps in mechanical coverage are visible.
- **how to audit:** Read each entry for a statement of how the defect surfaced. Where absent, note it. Where present and the route was human review, note it as a candidate for the ratchet: a defect class that only review catches is a class no script yet decides, which is exactly the input `R-GRD-004` asks for. The repository's log already does this in places, including an entry that names the failure mode explicitly as completing a table by inference rather than by reading the record that held the identities.
- **evidence required:** the entry lacking a detection route, or the entry whose route is human-only, with a one-line suggestion of the check that would have caught it.
- **not in scope:** any assessment of the author's or reviewer's competence, care, or judgment; this rule never blocks and never attaches blame.

---

# R-CMP — Comparability declarations

### R-CMP-001 — Every comparison declares a shared comparability basis
- **class:** HARD
- **deterministic_check:** C-CMP-001
- **applies_to:** every statement that compares two or more computed quantities — a difference, ratio, ordering, agreement claim, or match claim.
- **invariant:** Every comparison states the basis on which its quantities are comparable, names one artifact per side fixing that basis, and is self-consistent with the basis it states.
- **how to audit:** For each comparison, find the declared basis: the theory fingerprint, the reference or zero the quantities share, the cell or population, the metric definition. Three HARD findings are available. First, no basis is declared. Second, the declared basis is not shared: each side names a different fixing artifact, or one side names none. Third, the document contradicts its own declaration elsewhere. The repository's log records the instance this generalizes — a defect state reported as matching a reference to seven millielectronvolts using absolute eigenvalues from two separate periodic calculations that share no common zero, later re-anchored on two declared bases with values an order of magnitude larger. The auditor checks that a basis is declared and internally consistent, and stops there.
- **evidence required:** the comparison as written with its location, the declared basis or a statement that none is declared, and the per-side artifacts fixing it — including the specific inconsistency where one exists.
- **not in scope:** which reference or alignment is physically correct, whether the chosen basis is the best one, and whether the compared quantities are in truth comparable — that determination belongs to the audited party and the auditor enforces only what the repository declares.

### R-CMP-002 — Quantities the repository declares incomparable are never presented as a comparison
- **class:** HARD
- **deterministic_check:** C-CMP-002
- **applies_to:** every document quoting quantities that the repository's own declarations place in different comparability classes, and every claim the repository has explicitly closed or banned.
- **invariant:** No document presents quantities from declared-incomparable classes as a comparison, and no document asserts a claim the repository has declared closed until the repository's own stated condition for reopening it is recorded as met.
- **how to audit:** Read the repository's comparability declarations and its list of closed or banned claims as given — for example a declared pair of theory fingerprints with a stated prohibition on quoting one alongside the other, or a named literature ordering declared closed until both legs are converged at identical fingerprint. Then sweep for violations: quantities from two declared classes joined by comparative language (versus, faster, lower, agrees with, reproduces), and assertions of a closed claim. For a closed claim, check the repository's own reopening condition against the artifacts, not against the claim's plausibility. Enforcement is purely textual and declaration-driven.
- **evidence required:** the declaration as written with its location, the violating text with its location, and the mapping showing which declared class each quoted quantity belongs to.
- **not in scope:** whether the declared classes really are incomparable, whether the ban is scientifically justified, and whether the closed claim happens to be true.

### R-CMP-003 — A statistic declares its population and the attributes its own pooling declaration makes load-bearing
- **class:** HARD
- **deterministic_check:** C-CMP-003
- **applies_to:** every statistic, gate, aggregate, and pooled or merged corpus, together with the ledger or manifest defining its members.
- **invariant:** Every statistic and gate declares the exact population it was computed over, and for each member attribute the repository's own pooling declaration makes load-bearing, that attribute is recorded per member as a measured value.
- **how to audit:** For each statistic or gate, compare the population declared in prose against the members actually used according to the artifact, and report silent scope reduction: the repository's log records a homogeneity gate reported as a full-pool result that in fact compared eighteen of twenty-eight members, the subset being a file-format accident rather than a chosen sample. Then read the repository's own pooling declarations to learn which attributes are load-bearing — for instance a standing rule that pools built by different samplers or relaxed to different depths are never merged — and verify each such attribute is recorded per member and measured, not asserted. The repository's log records the corresponding failure: two batches at different relaxation depths pooled, producing an apparent population offset later reproduced exactly by re-relaxing to the tighter target. Where several counts over the same set appear in prose with different meanings, require the ledger to be the single authority and each count to name its meaning.
- **evidence required:** the statistic and its declared population, the actual member list from the artifact, and for each load-bearing attribute either the per-member measured record or its absence.
- **not in scope:** whether pooling is statistically valid, whether the sampler or relaxation depth was well chosen, whether the significance scale is appropriate, and whether the resulting statistic supports its conclusion.

---

# R-GRD — Guard and tooling integrity

### R-GRD-001 — A guard's verdict must be shown to track the condition it guards
- **class:** HARD
- **deterministic_check:** C-GUARD-001
- **applies_to:** every guard, preflight, integrity check, regression check, and verification script in the repository, and the Tier-0 checker itself.
- **invariant:** Every guard is demonstrated on committed fixtures to report failure when its condition holds and success when it does not, and its verdict is derived from the artifacts its condition actually concerns.
- **how to audit:** For each guard, find the fixture or recorded demonstration that it fires on the real condition. Absence of any negative demonstration is HARD: a guard never shown to fail provides no information, and a guard that lies is worse than no guard. Then read the guard's implementation against its stated condition and report mismatches that make its verdict independent of the condition — the repository's log records a produced-nothing guard that globbed a filename pattern the producing script never writes, and so reported failure on a run that had succeeded on every item. The exemplary form is also recorded there: a preflight tool validated against all five historical bad invocations and the one good invocation, which is the standard this rule asks for. For the Tier-0 checker, this rule is the only permitted route to a finding about a check, and it is a finding about fixtures and logic, never a re-verdict on the subject.
- **evidence required:** the guard, its stated condition, the missing or inadequate fixture, and — for a logic mismatch — the specific line whose behaviour does not depend on the condition, with a concrete input on which the guard's verdict is wrong.
- **not in scope:** whether the condition is worth guarding, whether the threshold it enforces is scientifically right, and whether a different verification strategy would be better.

### R-GRD-002 — A tool's own failure is never reported as the subject's failure
- **class:** HARD
- **deterministic_check:** C-GUARD-002
- **applies_to:** every wrapper, runner, guard, and parser that reports a verdict about something else, and every status derived from such a report.
- **invariant:** Every tool distinguishes its own malfunction from the condition it inspects, and reports a malfunction as a tool error rather than as a subject failure or a subject success.
- **how to audit:** For each reporting tool, trace how it obtains its verdict and identify paths on which the tool's own failure is indistinguishable from the subject's. Require an explicit check of the subordinate step's health before its output is interpreted. Two shapes are recorded in this repository. First, a flag guard that invoked a driver's help output, found no flags, and reported an unaccepted flag when the real cause was an import error that had crashed the help invocation — the fix being to check the exit code first and report an import failure as such. Second, a job that died after its science had already succeeded because the runner aborted on a non-matching search in an unrelated line, conflating the wrapper's exit status with the computation's outcome. Both directions are findings: a tool error read as subject failure, and a tool error read as subject success.
- **evidence required:** the tool, the code path where its own failure is indistinguishable from the subject's verdict, and a concrete invocation demonstrating the conflation.
- **not in scope:** whether the subject actually succeeded — that is what the repaired tool is for — and whether the tool's implementation language or structure is good.

### R-GRD-003 — A literal-string check must not become the reason stale text survives
- **class:** HARD
- **deterministic_check:** C-PIN-001
- **applies_to:** every check, test, or verification that asserts the presence or absence of exact text in a living document, and every retraction whose verification is such a check.
- **invariant:** No literal-text assertion over a living document can be satisfied only by leaving a claim uncorrected, and no literal-text assertion is accepted as verification that a claim has been swept.
- **how to audit:** This rule has two halves and both are HARD.

  The first half is the trap. Enumerate every literal-text assertion in the check suite and locate the document text it pins. Then ask what happens when that text must change because the claim it contains is corrected: if the check would fail on the corrected wording, the check has created a standing incentive to leave the stale sentence in place, and the check — not the writer — becomes the reason the text survives. A check may pin the numbers of a historical incident, a retraction banner that must not disappear, or an invariant's statement. A check may **not** pin the prose of a claim that is still live and therefore still correctable. When the auditor finds a live claim pinned by literal text, the finding is against the check, and its remedy is to re-pin the check to the incident's numbers or to the retraction marker rather than to the sentence. The same reasoning applies to a check that pins a *count* in prose: it freezes the prose instead of measuring the artifact, which is `R-EVD-004` in the check suite.

  The second half is the false assurance. Where a retraction's verification is a literal-string search, treat it as unverified: the repository's log records a retracted conclusion that survived in an abstract in paraphrase precisely because verification had matched literal strings only, and records the corrective form — a regex sweep across every result document with each hit examined for retraction context, reporting how many candidates were legitimate and how many were real. A retraction verified by literal matching alone is a HARD finding under this rule, in addition to any `R-COR-001` finding for the surviving text itself.
- **evidence required:** the check and the exact string it pins, the document text pinned, and either the demonstration that correcting the claim would break the check, or the retraction whose verification is literal-only together with the paraphrase the literal search cannot reach.
- **not in scope:** how the claim should be reworded, whether the retraction was warranted, and whether the pinned numbers are physically right.

### R-GRD-004 — Every check declares the rule it enforces and the incident it pins
- **class:** HARD
- **deterministic_check:** C-CHKID-001
- **applies_to:** the Tier-0 deterministic checker's check definitions and `check_report.json`, and the repository's own regression suite.
- **invariant:** Every check declares the rule ID it enforces and the incident or invariant it pins, and every `C-*` ID appearing in a report is declared by exactly one check definition.
- **how to audit:** Read the check definitions against the report. Flag a check with no declared rule ID, a check citing a rule ID absent from this rulebook, a `C-*` ID appearing in the report but declared nowhere, and the same `C-*` ID declared by two definitions. Then check the pinning: this repository's own regression suite holds that every numbered group fires on an actual historical incident rather than a hypothetical, and a check that pins nothing real is a check whose failure nobody can interpret. Traceability in both directions is the spine of the ratchet — without it, a proposed check cannot be shown to have been implemented, and a passing report cannot be mapped back to the rules it discharges.
- **evidence required:** the check definition or report entry, the missing or unresolvable rule ID, or the duplicate declaration with both locations.
- **not in scope:** whether the check's threshold is scientifically right, and whether the incident it pins was scientifically important.

### R-GRD-005 — Recommend a deterministic check for any defect class caught only by reading
- **class:** SOFT
- **deterministic_check:** none
- **applies_to:** the auditor's own coverage of this rulebook against the Tier-0 check suite.
- **invariant:** Every rule the auditor could apply only by reading, with no Tier-0 check deciding it, is reported with a concrete proposal for the check that would decide it next cycle.
- **how to audit:** After completing the pass, list the rules whose `deterministic_check` is `none` or whose check reported SKIP or ERROR, and for each state whether a script could decide it and how. This is the unprompted half of the ratchet: the mandatory half is the per-finding `proposed_check` required for HARD judgment findings, and this rule covers the classes where no defect was found but no script is watching either. Keep proposals concrete — the artifacts to read, the condition to decide, the fixture that would make the check fail.
- **evidence required:** the rule, why no script currently decides it, and either a concrete proposed check or a statement that the rule is irreducibly judgment-shaped.
- **not in scope:** any recommendation about scientific method, additional calculations, different thresholds, or better experiments; proposals here concern verification tooling only.

---

# R-NAV — Navigation and canonical-index integrity

### R-NAV-001 — The declared canonical index carries every current conclusion
- **class:** HARD
- **deterministic_check:** C-NAV-001
- **applies_to:** whatever document the repository declares to be its canonical index of conclusions, and every document holding a current conclusion.
- **invariant:** Every conclusion the repository presents as current is represented in the declared canonical index, and every row of that index resolves to the artifact holding that conclusion.
- **how to audit:** Take the repository's own declaration of which document is canonical. Enumerate current conclusions using the repository's own status vocabulary — a document declaring a result established, bounded, resolved, or otherwise current — and check each appears in the index. Then check the reverse direction: every index row names an authoritative artifact and that artifact still states what the row says. An index that omits a live conclusion is HARD; so is an index row whose claimed status differs from the artifact it points to, which overlaps `R-STA-002` and should be filed under whichever the exhibit fits best, once. The failure mode this generalizes is recorded in the repository's log: a correction that reached a result document but not the self-declared canonical index.
- **evidence required:** the canonical index, the conclusion and the document holding it, and the demonstration that no index row covers it — or the row whose status the target artifact contradicts.
- **not in scope:** whether the conclusion deserves to be current, whether it is scientifically sound, and how the index ought to be organised.

### R-NAV-002 — An authoritative pointer never resolves to a superseded document
- **class:** HARD
- **deterministic_check:** C-NAV-002
- **applies_to:** every pointer a document presents as authoritative — index rows, file-inventory tables of authoritative documents, README navigation, "see" references for current results.
- **invariant:** No pointer presented as authoritative resolves to a document that carries a superseding banner, is listed in the repository's own do-not-cite list, or has been replaced by a named successor.
- **how to audit:** Build the repository's superseded set from its own markers and its own do-not-cite list, then resolve every authoritative pointer against it. A file-inventory row naming a document as the authoritative result for a question while another section declares that document superseded by a named successor is HARD — and this repository contains that exact shape, an inventory row still naming the earlier corpus result after the merged corpus was declared authoritative. Also flag a pointer to a document marked provisional where the pointer presents it as authoritative without qualification.
- **evidence required:** the pointer with its location, the target document, and the marker or list entry establishing the target as superseded, together with the named successor.
- **not in scope:** which document ought to be authoritative on scientific grounds, and whether the successor's result is better.

### R-NAV-003 — Self-declared counts and enumerations match reality
- **class:** HARD
- **deterministic_check:** C-NAV-003
- **applies_to:** every count, tally, or enumeration a document declares about an artifact it does not itself contain — member counts, row counts, path counts, check-group counts, log-entry counts, image counts.
- **invariant:** Every self-declared count equals the count of the artifact it describes, and every declared enumeration is complete, without gaps or duplicate identifiers.
- **how to audit:** For each declared count, count the artifact and compare. Counts of the same thing appearing in different documents must agree: this repository declares its regression suite's group count in three places and the numbers do not all match, which is the canonical shape of this defect. Then check enumerations for gaps and duplicates — a log declaring a number of entries whose identifiers skip a value, or reuse one, is HARD. Enumeration *ordering* anomalies, such as an entry filed out of sequence, are reported at SOFT under this rule: they impede navigation without making any count false. Prose counts must never be the authority where a ledger exists; the repository's own standing rule requires sample-size and pool counts to be read from the manifest, never from prose, and a document quoting a count with no ledger citation is a finding under `R-EVD-003`.
- **evidence required:** the declared count with its location, the recounted value with the command that produced it, and every other location declaring a conflicting count.
- **not in scope:** whether the count is large enough for any scientific purpose, and whether the enumerated items should exist.

### R-NAV-004 — A current conclusion should reach its raw evidence without passing through a superseded document
- **class:** SOFT
- **deterministic_check:** none
- **applies_to:** the navigation path from the canonical index to raw evidence for each current conclusion.
- **invariant:** A reader starting at the canonical index can reach the raw evidence for any current conclusion through documents that are all current.
- **how to audit:** For each index row, walk the pointer chain to the raw data and note where the path passes through a document the repository marks superseded, provisional, or historical, and note chains long enough that the raw evidence is effectively unreachable. Report as navigation ergonomics. Where the chain is broken rather than merely awkward, the finding belongs to `R-EVD-002` or `R-NAV-002` instead.
- **evidence required:** the conclusion, the pointer chain as walked, and the specific hop that leaves the current set.
- **not in scope:** how the repository ought to structure its documents, and any judgment about the science at the end of the chain; this rule never blocks.

---

# R-PRO — Procedure adherence

### R-PRO-001 — Two-step staging before irreversible or expensive action
- **class:** HARD
- **deterministic_check:** C-PRO-001
- **applies_to:** every irreversible or expensive action — a production job submission, a cluster launch, a destructive migration, anything the repository's own rules place behind staging.
- **invariant:** For every such action, a staging record naming the exact inputs by digest was committed strictly before the action's execution trace, and a preflight result against those same digests reports success.
- **how to audit:** For each action, locate the staging record and the execution trace and establish the order from git history — the staging commit must be an ancestor of the commit carrying the execution record, and its digests must equal those in the execution record and in any remote-verification record. Then locate the preflight result and confirm it ran against the same digests. This repository demonstrates the intended form: staging manifests committed before submission, remote digests verified in place for input, harness, and reference before the tasks were reported running, with an in-job digest gate exiting non-zero on mismatch. Its failure log demonstrates the cost of skipping it — five consecutive failed submissions of one job from invented flags, a missing required argument, and unstaged modules, each of which a preflight would have caught before the queue.
- **evidence required:** the action, the staging commit and the execution commit with their order shown, the digests on each side, and the preflight result or its absence.
- **not in scope:** whether the action was scientifically worth running, whether its cost was justified, and whether the inputs describe a good calculation.

### R-PRO-002 — A declared gate records per-condition evidence
- **class:** HARD
- **deterministic_check:** C-PRO-002
- **applies_to:** every gate, entry criterion, acceptance criterion, or checklist the repository declares as controlling an action.
- **invariant:** Every condition of a declared gate carries its own recorded verdict with a citation to the artifact establishing it, and the gate's overall verdict is the conjunction of those recorded conditions.
- **how to audit:** Enumerate the gate's conditions from the document that declares them — for example a five-condition entry gate — and for each require a recorded verdict and a cited artifact. A condition marked passing by assertion alone, or by construction with no artifact, is HARD. Check the conjunction: an overall pass with any condition unrecorded, failing, or partially met is HARD. Check also that a passed gate is not conflated with an authorisation to act where the repository declares those separate — this repository states explicitly that a passed gate is not an approved launch — and that where a condition was closed later than the others, the record says so.
- **evidence required:** the gate, the condition lacking a verdict or a cited artifact, and the overall verdict as recorded.
- **not in scope:** whether the gate's conditions are the right ones, whether they are sufficient to protect the science, and whether a passing condition was measured against a sensible threshold.

### R-PRO-003 — The audit trail is append-only
- **class:** HARD
- **deterministic_check:** C-PRO-003
- **applies_to:** every store the repository declares append-only — per-advance archives, snapshot series, event logs, retraction logs, execution-failure logs, and audit-cycle directories.
- **invariant:** Entries in an append-only store are only ever added; no existing entry's bytes change and no entry is removed.
- **how to audit:** For each declared append-only path, walk its git history and inspect every modifying commit. Additions are permitted; deletions and in-place modifications of existing entries are HARD. Where the store has a declared indexing convention, verify it holds — this repository declares that an archive snapshot at a given index holds the band with the corresponding iteration counter, verified on the first snapshots with distinct content digests and appends only on content change, so an index that no longer maps to its declared meaning is a finding. A wording error in a progress message about a convention is not a data finding and should be reported at SOFT under `R-NAV-003` if at all.
- **evidence required:** the append-only path, the commit modifying or removing an existing entry, and the diff showing the non-additive change.
- **not in scope:** whether the archived intermediates are scientifically useful, and whether the retention policy is right.

### R-PRO-004 — No commit asserts a substantive event without a content change
- **class:** HARD
- **deterministic_check:** C-PRO-004
- **applies_to:** every commit whose message asserts a substantive event — a launch, a fix, a retraction, a verification, a gate closure, a sweep, a test pass.
- **invariant:** Every commit asserting a substantive event changes content consistent with that assertion, touching at least one artifact the message names or implies.
- **how to audit:** For each such commit, inspect its tree change. An empty commit asserting an event is HARD. A commit whose message asserts a fix, a verification, or a sweep while touching no artifact of the kind the message names is HARD — for example a message claiming a repo-wide sweep that modifies one file, or a message claiming a verification that adds no verification artifact. Keep the demonstration mechanical: name the artifact class the message asserts and show that the tree change contains nothing of that class. Do not extend this to judging whether the change was a *good* fix; a change of the asserted kind, however small, discharges this rule.
- **evidence required:** the commit hash, the asserted event quoted from the message, and the tree change (empty, or containing no artifact of the asserted class).
- **not in scope:** whether the fix works, whether the change is complete as science, and whether the commit granularity is good practice — completeness of a correction is `R-COR-004`, not this rule.

---

## Amending this rulebook

Version bumps, applied to `rulebook_version` in this file:

| change | bump |
|---|---|
| a rule added, removed, or reclassified between HARD and SOFT | **minor** |
| a rule's `deterministic_check` binding changed | **minor** |
| a family added | **minor** |
| wording clarified without changing what the invariant tests | **patch** |
| typography, ordering, or table formatting | **patch** |
| an invariant's meaning changed, or a rule ID retired or repurposed | **major** |

Rules for amendments:

1. **Rule IDs are permanent.** A retired rule is marked retired in place; its ID is never reused
   and never reassigned to a different invariant. Renumbering is a major bump and requires the
   controller to map old IDs to new ones for open findings.
2. **Every rule keeps all seven fields**, including `not in scope`. A rule without a `not in scope`
   line cannot be locked — it is the guardrail that keeps the auditor out of the science.
3. **SOFT rules declare `deterministic_check: none`.** If a script can decide a rule, it is HARD.
   The locker enforces this.
4. **Non-`none` check IDs are unique across rules.** Two rules may not claim the same `C-*` ID; a
   check that would serve two rules must be split.
5. **The lock file is regenerated in the same change.** Run `python3 lock_rulebook.py`, commit
   `rulebook.lock.json` alongside the edited markdown, and confirm
   `python3 lock_rulebook.py --check` exits 0. A commit that edits this file without regenerating
   the lock is a defect under `R-PRO-004` against this system's own repository.
6. **The controller config is updated in the same change** to reference the new
   `rulebook_version` and `rulebook_sha256`, so that a cycle can never run against a rulebook
   version its policy does not know. Findings emitted under a version the controller does not
   recognise must be rejected by the report validator, not silently accepted.
7. **Adding a family** requires adding its prefix to `KNOWN_FAMILIES` in `lock_rulebook.py` and to
   the family table above, in the same change.
8. **A new rule states the failure it generalizes.** Rules in this book are derived from recorded
   incidents, not from imagination; a proposed rule with no incident behind it should be weighed
   against the cost of one more thing for the auditor to check every cycle.
