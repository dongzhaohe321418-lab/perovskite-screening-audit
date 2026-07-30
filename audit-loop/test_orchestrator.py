"""Unit tests for orchestrator logic that the end-to-end selftest cannot isolate."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
import yaml

LOOP_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(LOOP_ROOT / "orchestrator"))
from orchestrator import Orchestrator  # noqa: E402


def make(tmp_path: Path, cycles: dict) -> Orchestrator:
    real = yaml.safe_load((LOOP_ROOT / "orchestrator" / "config.yaml").read_text())
    state = tmp_path / "state"
    (state / "controller").mkdir(parents=True)
    (state / "controller" / "state.json").write_text(json.dumps({"cycles": cycles}))
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
