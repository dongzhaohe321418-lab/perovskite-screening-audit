"""Unit tests for orchestrator logic that the end-to-end selftest cannot isolate."""
from __future__ import annotations

import json
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
