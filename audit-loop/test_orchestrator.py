"""Unit tests for orchestrator logic that the end-to-end selftest cannot isolate."""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

LOOP_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(LOOP_ROOT / "orchestrator"))
from orchestrator import Orchestrator  # noqa: E402


def make(tmp_path: Path, cycles: dict, events: list | None = None) -> Orchestrator:
    real = yaml.safe_load((LOOP_ROOT / "orchestrator" / "config.yaml").read_text())
    state = tmp_path / "state"
    (state / "controller").mkdir(parents=True)
    (state / "controller" / "state.json").write_text(
        json.dumps({"cycles": cycles, "event_log": events or []}))
    (state / "secrets.env").write_text("GITHUB_WEBHOOK_SECRET=test\n")
    config = dict(real)
    config["paths"] = {**real["paths"], "state_dir": str(state),
                       "secrets_env": str(state / "secrets.env")}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    return Orchestrator(path)


def final(cycle_id: str, commit: str) -> dict:
    return {"cycle_id": cycle_id, "science_commit": commit, "status": "FINAL"}


def test_tier0_base_is_the_newest_cycle_not_the_highest_sha(tmp_path):
    """Ordering by SHA sorts hex strings; the newest cycle is the one to diff from."""
    cycles = {
        "CYCLE-000001": final("CYCLE-000001", "f" * 40),
        "CYCLE-000002": final("CYCLE-000002", "0" * 39 + "a"),
    }
    assert make(tmp_path, cycles).tier0_base_commit() == "0" * 39 + "a"


def test_tier0_base_is_none_before_any_final_cycle(tmp_path):
    assert make(tmp_path, {}).tier0_base_commit() == "NONE"


def test_tier0_base_ignores_unfinalized_cycles(tmp_path):
    cycles = {
        "CYCLE-000001": final("CYCLE-000001", "1" * 40),
        "CYCLE-000002": {"cycle_id": "CYCLE-000002", "science_commit": "2" * 40,
                         "status": "CODEX_TASK_CREATED"},
    }
    assert make(tmp_path, cycles).tier0_base_commit() == "1" * 40


def test_readme_counts_match_reality():
    """R-NAV-003 applied to ourselves: a self-declared count must be true.

    Three counts in the README drifted once check_action and C-TREESAFE-001
    landed, and were caught by an agent reading the file rather than by anything
    here. This pins them.
    """
    readme = (LOOP_ROOT / "README.md").read_text(encoding="utf-8")
    tools = len(set(re.findall(
        r'"(audit_status|get_pending_review|submit_disposition|request_audit'
        r'|acknowledge_escalation|notify_pi|check_action)"',
        (LOOP_ROOT / "mcp" / "audit_mcp_server.py").read_text(encoding="utf-8"))))
    checks = len(re.findall(
        r"^@check\(", (LOOP_ROOT / "checks" / "deterministic_checks.py").read_text(
            encoding="utf-8"), re.MULTILINE))
    assert f"{tools} 个工具" in readme, f"README does not state {tools} MCP tools"
    assert f"{checks} 项 C-* 检查" in readme, f"README does not state {checks} Tier-0 checks"
    assert f"Tier-0 {checks} 项检查" in readme
    assert f"Tier-0 覆盖率 {checks}/27" in readme


def blocker_state(tmp_path: Path, events: list, cycles: dict | None = None) -> Orchestrator:
    return make(tmp_path, cycles or {}, events)


def opened_event(finding_id="F-001", cycle="CYCLE-000001", when="2026-07-30T00:00:00+00:00"):
    return {"event": "FINDING_OPENED", "finding_id": finding_id, "project_id": "p",
            "cycle_id": cycle, "blocked_scopes": ["*"], "timestamp": when,
            "data": {"blocking": True}}


def disposition_event(finding_id, disposition, cycle="CYCLE-000001"):
    return {"event": "DISPOSITION_RECORDED", "finding_id": finding_id, "project_id": "p",
            "cycle_id": cycle, "timestamp": "2026-07-30T00:00:00+00:00",
            "data": {"disposition": disposition}}


@pytest.mark.parametrize("disposition", ["DISAGREE_WITH_EVIDENCE", "NEED_PI_DECISION"])
def test_a_dispute_escalates_without_waiting_for_more_cycles(tmp_path, disposition):
    """Two agents contradicting each other is a PI decision, not a loop to grind.

    This is the hole a cycle counter alone leaves: a disputed finding produces no
    further commits, so no further cycles, so a cycle-based counter never fires
    while the finding blocks production indefinitely.
    """
    recent = dt.datetime.now(dt.timezone.utc).isoformat()
    orch = blocker_state(
        tmp_path,
        [opened_event(when=recent), disposition_event("F-001", disposition)],
        {"CYCLE-000001": {"cycle_id": "CYCLE-000001", "science_commit": "a" * 40,
                          "status": "FINAL"}},
    )
    orch.scan_escalations()

    escalations = json.loads((orch.state_dir / "escalations.json").read_text())["escalations"]
    assert [e["finding_id"] for e in escalations] == ["F-001"]
    assert disposition in escalations[0]["reason"]
    assert orch._open_escalations() == ["ESC-0001"]


def test_a_long_open_blocker_escalates_on_age_alone(tmp_path):
    stale = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=48)).isoformat()
    orch = blocker_state(tmp_path, [opened_event(when=stale)])
    orch.scan_escalations()

    escalations = json.loads((orch.state_dir / "escalations.json").read_text())["escalations"]
    assert len(escalations) == 1
    assert "48h" in escalations[0]["reason"] or "blocking for" in escalations[0]["reason"]


def test_a_fresh_undisputed_blocker_does_not_escalate(tmp_path):
    recent = dt.datetime.now(dt.timezone.utc).isoformat()
    orch = blocker_state(tmp_path, [opened_event(when=recent)])
    orch.scan_escalations()

    assert not (orch.state_dir / "escalations.json").exists()
    assert orch._open_escalations() == []


def test_a_verified_closure_clears_the_blocker(tmp_path):
    stale = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=48)).isoformat()
    orch = blocker_state(tmp_path, [
        opened_event(when=stale),
        {"event": "FINDING_VERIFIED_CLOSED", "finding_id": "F-001", "project_id": "p",
         "cycle_id": "CYCLE-000002", "timestamp": stale, "data": {}},
    ])
    assert orch.active_blockers() == {}
    orch.scan_escalations()
    assert not (orch.state_dir / "escalations.json").exists()


def test_doctor_never_reports_idle_while_a_blocker_denies_actions(tmp_path, capsys):
    """R-GRD-001 turned on ourselves: a guard that says all-clear during a live
    block is worse than no guard. doctor used to print exactly that."""
    recent = dt.datetime.now(dt.timezone.utc).isoformat()
    orch = blocker_state(
        tmp_path,
        [opened_event(when=recent), disposition_event("F-001", "DISAGREE_WITH_EVIDENCE")],
        {"CYCLE-000001": {"cycle_id": "CYCLE-000001", "science_commit": "a" * 40,
                          "status": "FINAL", "disposition_status": "RECORDED",
                          "audit_result": {"decision": "BLOCK", "findings": [
                              {"finding_id": "F-001"}]}}},
    )
    orch.doctor()

    out = capsys.readouterr().out
    assert "Idle" not in out
    assert "ACTIVE BLOCKERS" in out
    assert "F-001" in out
    assert "DISAGREE_WITH_EVIDENCE" in out
