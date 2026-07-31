#!/usr/bin/env python3
"""Three-hourly review: decide whether the PI actually needs to intervene.

Returns exit 0 when the loop is healthy and unattended operation should continue,
exit 1 when something needs a human. Prints a short report either way. Silence is
not a health signal, so it always prints something.
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "orchestrator"))
from orchestrator import Orchestrator  # noqa: E402

o = Orchestrator(ROOT / "orchestrator" / "config.yaml")
state = o.controller_state()
cycles = state.get("cycles", {})
blockers = o.active_blockers()
escalations = o._open_escalations()
queued = len(list(o.spool.glob("evt-*.json")))
pending = sorted(p.stem for p in o.pending_dir.glob("CYCLE-*.json"))
# A cycle the PI has voided in writing is settled, not stuck: re-reporting it every
# three hours would train the reader to ignore the alert that matters.
stuck = [c["cycle_id"] for c in cycles.values()
         if c.get("status") == "AUDIT_OUTPUT_INVALID"
         and not (o.cycles_dir / c["cycle_id"] / "VOIDED.md").exists()]
running = subprocess.run(["pgrep", "-f", "codex.*exec"], capture_output=True).returncode == 0

needs_pi: list[str] = []
if escalations:
    needs_pi.append(f"{len(escalations)} escalation(s) OPEN — auto re-audit is PAUSED: "
                    + ", ".join(escalations))
for fid, b in sorted(blockers.items()):
    age = o._age_hours(b["opened_at"])
    if age >= 48:
        needs_pi.append(f"{fid} has blocked for {age:.0f}h")
if stuck:
    needs_pi.append(f"cycle(s) stuck at AUDIT_OUTPUT_INVALID: {', '.join(stuck)}")
if pending and not running:
    newest = max((c for c in cycles.values() if c["cycle_id"] in pending),
                 key=lambda c: c["cycle_id"], default=None)
    if newest:
        age = o._age_hours(newest.get("updated_at", ""))
        if age >= 6:
            needs_pi.append(f"{newest['cycle_id']} has awaited a disposition for {age:.0f}h")
if queued >= 5 and not running:
    needs_pi.append(f"{queued} events queued with no audit running")

lines = [
    f"audit-loop review {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}",
    f"  cycles: {len(cycles)} | active blockers: {len(blockers)} | "
    f"escalations OPEN: {len(escalations)} | queued: {queued} | "
    f"codex running: {'yes' if running else 'no'}",
]
for fid, b in sorted(blockers.items()):
    lines.append(f"  {fid} open {o._age_hours(b['opened_at']):.0f}h "
                 f"[{b['disposition'] or 'no disposition'}] {','.join(b['blocked_scopes'])}")
if needs_pi:
    lines.append("  NEEDS YOU:")
    lines += [f"    - {r}" for r in needs_pi]
else:
    lines.append("  healthy — no intervention needed")
report = "\n".join(lines)
print(report)
(o.logs_dir / "health_review.log").open("a", encoding="utf-8").write(report + "\n\n")

if needs_pi:
    subprocess.run(["osascript", "-e",
                    'display notification "{}" with title "Audit Loop: 需要你介入"'.format(
                        needs_pi[0].replace('"', "'")[:170])], check=False)
    # Outbound SMTP is refused by the recipient's provider from a residential IP, so
    # the off-machine channel is an HTTPS push to a private topic instead. It carries
    # no secrets: only what the review already printed.
    topic_file = ROOT / "state" / "ntfy_topic.txt"
    if topic_file.exists():
        topic = topic_file.read_text(encoding="utf-8").strip()
        subprocess.run(
            ["curl", "-s", "-m", "20",
             "-H", "Title: Audit Loop 需要你介入",
             "-H", "Priority: high",
             "-H", "Tags: warning",
             "-d", "\n".join(needs_pi)[:900],
             f"https://ntfy.sh/{topic}"],
            capture_output=True, check=False)
sys.exit(1 if needs_pi else 0)
