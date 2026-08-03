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
| [CYCLE-000005](cycles/CYCLE-000005.md) | `b7de47840a74` | BLOCK | 2 | RECORDED | 3 |
| [CYCLE-000006](cycles/CYCLE-000006.md) | `4aed10a97d48` | BLOCK | 1 | RECORDED | 2 |
| [CYCLE-000007](cycles/CYCLE-000007.md) | `4ccb0cd6c4fa` | PASS_WITH_CAVEATS | 1 | RECORDED | 1 |
| [CYCLE-000008](cycles/CYCLE-000008.md) | `af0dc58713b9` | PASS | 0 | INVALID | 1 |
| [CYCLE-000009](cycles/CYCLE-000009.md) | `a75e2f7f2d0d` | PASS | 0 | TASK_CREATED | 2 |
| [CYCLE-000010](cycles/CYCLE-000010.md) | `e967e47176f2` | PASS_WITH_CAVEATS | 1 | RECORDED | 0 |
| [CYCLE-000011](cycles/CYCLE-000011.md) | `c1e973cac911` | PASS_WITH_CAVEATS | 1 | RECORDED | 0 |
| [CYCLE-000012](cycles/CYCLE-000012.md) | `89db467e627b` | BLOCK | 1 | RECORDED | 1 |
| [CYCLE-000013](cycles/CYCLE-000013.md) | `c1c6bac94a22` | BLOCK | 1 | RECORDED | 0 |
| [CYCLE-000014](cycles/CYCLE-000014.md) | `62160f0b05f1` | PASS | 0 | TASK_CREATED | 1 |
| [CYCLE-000015](cycles/CYCLE-000015.md) | `c6372d99c5c3` | BLOCK | 1 | RECORDED | 0 |
| [CYCLE-000016](cycles/CYCLE-000016.md) | `a9c5f0f5c90a` | BLOCK | 1 | RECORDED | 1 |
| [CYCLE-000017](cycles/CYCLE-000017.md) | `39fb71f74050` | BLOCK | 3 | RECORDED | 0 |
| [CYCLE-000018](cycles/CYCLE-000018.md) | `27dd4bd297ac` | BLOCK | 3 | RECORDED | 0 |
| [CYCLE-000019](cycles/CYCLE-000019.md) | `a6bddfe82224` | BLOCK | 1 | TASK_CREATED | 2 |

## Totals

- cycles finalized: 18
- findings verified closed: 19
- audit input tokens: 47,233,806

## Files

- `cycles/CYCLE-*.md` — one page per cycle: findings, disposition, closures, cost
- `dispositions/CYCLE-*.json` — the executor's answer, verbatim as the controller accepted it
- `action_ledger.jsonl` — every admission-gate consultation and its decision
- `escalations.json` — findings escalated to the principal
- `INCIDENTS.md` — defects in the supervision system itself, both sides
