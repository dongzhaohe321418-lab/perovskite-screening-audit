# Audit ledger — executor side

What the auditor found is on the [`audit`](../../tree/audit) branch and is
immutable. This branch records the other half: what the executor answered,
what the gate permitted, and what each cycle cost. Generated; do not edit.

| cycle | audited commit | decision | findings | disposition | closed here |
|---|---|---|---|---|---|
| [CYCLE-000001](cycles/CYCLE-000001.md) | `81fd505e71b8` | BLOCK | 7 | RECORDED | 0 |
| [CYCLE-000002](cycles/CYCLE-000002.md) | `bfece650948a` | BLOCK | 4 | RECORDED | 5 |
| [CYCLE-000003](cycles/CYCLE-000003.md) | `ddaca3fc36e3` | AUDIT_OUTPUT_INVALID | 0 | NOT_STARTED | 0 |
| [CYCLE-000004](cycles/CYCLE-000004.md) | `746564b69191` | BLOCK | 3 | RECORDED | 0 |
| [CYCLE-000005](cycles/CYCLE-000005.md) | `b7de47840a74` | BLOCK | 2 | TASK_CREATED | 3 |

## Totals

- cycles finalized: 4
- findings verified closed: 8
- audit input tokens: 10,487,171

## Files

- `cycles/CYCLE-*.md` — one page per cycle: findings, disposition, closures, cost
- `dispositions/CYCLE-*.json` — the executor's answer, verbatim as the controller accepted it
- `action_ledger.jsonl` — every admission-gate consultation and its decision
- `escalations.json` — findings escalated to the principal
