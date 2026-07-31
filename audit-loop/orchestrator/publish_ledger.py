#!/usr/bin/env python3
"""Publish the executor-side record to the audit repository's `ledger` branch.

The `audit` branch carries what the auditor found. Accountability needs the other
half: what the executor answered, what it was permitted to do, and what each cycle
cost. Those live in controller state and local ledgers, which are not publishable
on their own — so this renders them into an orphan `ledger` branch.

It must be a separate branch. The controller rejects any push to `audit` whose
diff touches anything outside `projects/<id>/cycles/<cycle_id>/` with one of six
allowed filenames, and `claude_disposition.json` is explicitly forbidden there so
the auditor can never fabricate the executor's answer. Writing these records to
`audit` would be rejected, and because the trusted head never advances past a
rejected commit, it would wedge the pipeline. Pushes to any other ref are ignored.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


def sh(args: list[str], cwd: Path | None = None, check: bool = True) -> str:
    return subprocess.run(args, cwd=cwd, check=check, capture_output=True,
                          text=True).stdout.strip()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def cycle_summary(cycle: dict[str, Any], state: dict[str, Any],
                  costs: dict[str, dict[str, Any]]) -> str:
    result = cycle.get("audit_result") or {}
    cid = cycle["cycle_id"]
    disposition = (state.get("dispositions") or {}).get(cid)
    events = [e for e in state.get("event_log", []) if e.get("cycle_id") == cid]
    closed = [e["finding_id"] for e in events if e["event"] == "FINDING_VERIFIED_CLOSED"]
    cost = costs.get(cid, {})

    lines = [
        f"# {cid}",
        "",
        "| | |",
        "|---|---|",
        f"| audited commit | `{cycle['science_commit']}` |",
        f"| decision | **{result.get('decision', cycle.get('status'))}** |",
        f"| audit report id | `{cycle.get('audit_report_id')}` |",
        f"| report sha256 | `{cycle.get('audit_report_sha256')}` |",
        f"| audit repo commit | `{cycle.get('audit_repo_commit')}` |",
        f"| parent receipt | `{cycle.get('parent_report_sha256') or '(first cycle)'}` |",
        f"| finalized | {cycle.get('updated_at')} |",
    ]
    if cost:
        lines.append(f"| cost | {cost.get('input_tokens', 0):,} in / "
                     f"{cost.get('output_tokens', 0):,} out, "
                     f"{cost.get('wall_seconds', 0):.0f}s |")
    lines += ["", "## Findings raised", ""]
    findings = result.get("findings", [])
    if findings:
        lines += ["| id | severity | title | blocked scopes |", "|---|---|---|---|"]
        for f in findings:
            scopes = ", ".join(f.get("blocked_scopes") or []) or "—"
            lines.append(f"| {f['finding_id']} | {f['severity']} | "
                         f"{f.get('title', '').replace('|', '/')} | {scopes} |")
    else:
        lines.append("None.")

    lines += ["", "## Executor disposition", ""]
    if disposition:
        lines += ["| finding | disposition | fix commit |", "|---|---|---|"]
        for item in disposition.get("findings", []):
            fix = item.get("fix_commit")
            lines.append(f"| {item['finding_id']} | {item['disposition']} | "
                         f"{'`' + fix + '`' if fix else '—'} |")
        lines.append("")
        lines.append(f"Report hash confirmed: `{disposition.get('report_sha256')}`")
    else:
        lines.append("Not yet answered.")

    lines += ["", "## Verified closures in this cycle", ""]
    lines.append(", ".join(f"`{f}`" for f in closed) if closed else "None.")
    lines.append("")
    return "\n".join(lines)


def build_index(state: dict[str, Any], costs: dict[str, dict[str, Any]]) -> str:
    cycles = sorted((c for c in state.get("cycles", {}).values()),
                    key=lambda c: c["cycle_id"])
    closed_by_cycle: dict[str, list[str]] = {}
    for e in state.get("event_log", []):
        if e["event"] == "FINDING_VERIFIED_CLOSED":
            closed_by_cycle.setdefault(e.get("cycle_id") or "", []).append(e["finding_id"])

    lines = [
        "# Audit ledger — executor side",
        "",
        "What the auditor found is on the [`audit`](../../tree/audit) branch and is",
        "immutable. This branch records the other half: what the executor answered,",
        "what the gate permitted, and what each cycle cost. Generated; do not edit.",
        "",
        "| cycle | audited commit | decision | findings | disposition | closed here |",
        "|---|---|---|---|---|---|",
    ]
    for c in cycles:
        r = c.get("audit_result") or {}
        cid = c["cycle_id"]
        closed = closed_by_cycle.get(cid, [])
        lines.append(
            f"| [{cid}](cycles/{cid}.md) | `{c['science_commit'][:12]}` | "
            f"{r.get('decision') or c.get('status')} | {len(r.get('findings', []))} | "
            f"{c.get('disposition_status')} | {len(closed)} |")

    total_in = sum(int(v.get("input_tokens") or 0) for v in costs.values())
    lines += [
        "",
        "## Totals",
        "",
        f"- cycles finalized: {sum(1 for c in cycles if c.get('status') == 'FINAL')}",
        f"- findings verified closed: {sum(len(v) for v in closed_by_cycle.values())}",
        f"- audit input tokens: {total_in:,}",
        "",
        "## Files",
        "",
        "- `cycles/CYCLE-*.md` — one page per cycle: findings, disposition, closures, cost",
        "- `dispositions/CYCLE-*.json` — the executor's answer, verbatim as the controller accepted it",
        "- `action_ledger.jsonl` — every admission-gate consultation and its decision",
        "- `escalations.json` — findings escalated to the principal",
        "- `INCIDENTS.md` — defects in the supervision system itself, both sides",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=str(Path(__file__).parent / "config.yaml"))
    ap.add_argument("--branch", default="ledger")
    ap.add_argument("--no-push", action="store_true")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    state_dir = Path(cfg["paths"]["state_dir"])
    audit_repo = Path(cfg["paths"]["audit_repo"])
    state = json.loads((state_dir / "controller" / "state.json").read_text(encoding="utf-8"))
    costs = {row["cycle_id"]: row for row in load_jsonl(state_dir / "cost_ledger.jsonl")}

    work = state_dir / "ledger-worktree"
    subprocess.run(["git", "worktree", "remove", "--force", str(work)],
                   cwd=audit_repo, capture_output=True, check=False)
    has_branch = subprocess.run(["git", "rev-parse", "--verify", "--quiet",
                                 f"refs/heads/{args.branch}"],
                                cwd=audit_repo, capture_output=True).returncode == 0
    if has_branch:
        sh(["git", "worktree", "add", "--quiet", str(work), args.branch], cwd=audit_repo)
    else:
        sh(["git", "worktree", "add", "--quiet", "--detach", str(work)], cwd=audit_repo)
        sh(["git", "checkout", "--orphan", args.branch], cwd=work)
        subprocess.run(["git", "rm", "-rf", "--cached", "."], cwd=work,
                       capture_output=True, check=False)
        for stale in work.iterdir():
            if stale.name != ".git":
                subprocess.run(["rm", "-rf", str(stale)], check=False)

    for sub in ("cycles", "dispositions"):
        (work / sub).mkdir(parents=True, exist_ok=True)
    (work / "INDEX.md").write_text(build_index(state, costs), encoding="utf-8")
    for cycle in state.get("cycles", {}).values():
        cid = cycle["cycle_id"]
        (work / "cycles" / f"{cid}.md").write_text(
            cycle_summary(cycle, state, costs), encoding="utf-8")
        disposition = (state.get("dispositions") or {}).get(cid)
        if disposition:
            (work / "dispositions" / f"{cid}.json").write_text(
                json.dumps(disposition, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for name in ("action_ledger.jsonl", "escalations.json"):
        src = state_dir / name
        if src.exists():
            (work / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    # The supervision system's own defects belong in the published record too: a
    # ledger that showed only the audited party's failures would be the less
    # honest document.
    incidents = Path(cfg["paths"]["audit_loop_root"]) / "INCIDENTS.md"
    if incidents.exists():
        (work / "INCIDENTS.md").write_text(incidents.read_text(encoding="utf-8"),
                                           encoding="utf-8")

    sh(["git", "add", "-A"], cwd=work)
    if not sh(["git", "status", "--porcelain"], cwd=work):
        print("ledger unchanged")
    else:
        sh(["git", "-c", "user.name=Audit Loop Controller",
            "-c", "user.email=audit-loop@local", "commit", "-m",
            f"ledger: executor-side record through "
            f"{max(state.get('cycles', {}), default='(none)')}"], cwd=work)
        head = sh(["git", "rev-parse", "--short", "HEAD"], cwd=work)
        print(f"ledger committed {head}")
        if not args.no_push and subprocess.run(
                ["git", "remote", "get-url", "origin"], cwd=audit_repo,
                capture_output=True).returncode == 0:
            pushed = subprocess.run(["git", "push", "origin", args.branch],
                                    cwd=work, capture_output=True, timeout=120)
            print("ledger pushed" if pushed.returncode == 0
                  else f"ledger push failed: {pushed.stderr.decode()[-120:]}")

    subprocess.run(["git", "worktree", "remove", "--force", str(work)],
                   cwd=audit_repo, capture_output=True, check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
