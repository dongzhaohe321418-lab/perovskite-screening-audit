# Audit ledger — executor side

What the auditor found is on the [`audit`](../../tree/audit) branch and is
immutable. This branch records the other half: what the executor answered,
what the gate permitted, and what each cycle cost. Generated; do not edit.

| cycle | audited commit | decision | findings | disposition | closed here |
|---|---|---|---|---|---|
| [CYCLE-000009](cycles/CYCLE-000009.md) | `cccccccccccc` | BLOCK | 1 | TASK_CREATED | 0 |

## Totals

- cycles finalized: 1
- findings verified closed: 0
- audit input tokens: 0

## Files

- `cycles/CYCLE-*.md` — one page per cycle: findings, disposition, closures, cost
- `dispositions/CYCLE-*.json` — the executor's answer, verbatim as the controller accepted it
- `action_ledger.jsonl` — every admission-gate consultation and its decision
- `escalations.json` — findings escalated to the principal
