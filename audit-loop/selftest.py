#!/usr/bin/env python3
"""End-to-end pipeline selftest against SCRATCH clones. Production repos and
state are never touched: it clones scienceRepo + auditRepo into a scratch dir,
writes a scratch config + secrets, runs a full simulated cycle
(science event -> controller cycle -> Tier-0 checks -> simulated codex ->
audit repo commit -> controller FINAL -> pending review), then submits a
disposition through the controller and checks escalation logic wiring.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

LOOP_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = LOOP_ROOT.parent


def sh(args, cwd=None, **kw):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True, **kw)


def main() -> int:
    scratch = Path(tempfile.mkdtemp(prefix="audit-loop-selftest.",
                                    dir="/private/tmp/claude-501/-Users-ericdong-Claude/86802547-5493-41c9-b71f-97dcfaf124ab/scratchpad"
                                    if Path("/private/tmp/claude-501").exists() else None))
    print(f"selftest scratch: {scratch}")
    science = scratch / "scienceRepo"
    audit = scratch / "auditRepo"
    state = scratch / "state"
    sh(["git", "clone", "--quiet", str(PROJECT_ROOT / "scienceRepo"), str(science)])
    sh(["git", "clone", "--quiet", "--branch", "audit",
        str(PROJECT_ROOT / "auditRepo"), str(audit)])
    audit_head = sh(["git", "rev-parse", "HEAD"], cwd=audit).stdout.strip()
    science_head = sh(["git", "rev-parse", "HEAD"], cwd=science).stdout.strip()

    state.mkdir()
    (state / "secrets.env").write_text(
        "\n".join(f"{k}=selftest-{k.lower()}" for k in
                  ["GITHUB_WEBHOOK_SECRET", "ACTION_API_TOKEN", "CLAUDE_API_TOKEN",
                   "PI_APPROVAL_TOKEN", "CONTROLLER_READ_TOKEN"]) + "\n")

    projects = {
        "projects": [{
            "project_id": "perovskite-screening",
            "science_repo": "perovskite-screening",
            "science_repo_full_name": "dongzhaohe321418-lab/perovskite-screening",
            "science_branch": "main",
            "audit_repo": "perovskite-screening-audit",
            "audit_repo_full_name": "dongzhaohe321418-lab/perovskite-screening-audit",
            "audit_branch": "audit",
            "audit_initial_commit": audit_head,
            "science_relevant_paths": [""],
        }]
    }
    import yaml
    (scratch / "projects.yaml").write_text(yaml.safe_dump(projects))
    real = yaml.safe_load((LOOP_ROOT / "orchestrator" / "config.yaml").read_text())

    config = {
        "paths": {
            "science_repo": str(science),
            "audit_repo": str(audit),
            "controller_root": str(PROJECT_ROOT / "science-audit-controller"),
            "audit_loop_root": str(LOOP_ROOT),
            "state_dir": str(state),
            "venv_python": str(LOOP_ROOT / ".venv" / "bin" / "python"),
            "secrets_env": str(state / "secrets.env"),
        },
        "project": {
            "project_id": "perovskite-screening",
            "science_branch": "main",
            "audit_branch": "audit",
            "science_repo_full_name": "dongzhaohe321418-lab/perovskite-screening",
            "audit_repo_full_name": "dongzhaohe321418-lab/perovskite-screening-audit",
        },
        "codex": {"command": "/bin/false", "args": [], "timeout_seconds": 60, "max_retries": 1},
        "sync": {"science_fetch": False, "audit_push": False},
        # Mirror production policy, or the harness silently tests weaker rules.
        "severity_floors": real["severity_floors"],
        "tier0_skip_allowed": real.get("tier0_skip_allowed", []),
        "limits": {"max_cycles_per_hour": 10, "escalate_after_unresolved_cycles": 1},
        "notifications": {"macos": False, "log_file": "notifications.log"},
    }
    config_path = scratch / "config.yaml"
    config_path.write_text(yaml.safe_dump(config))

    # PROJECT_CONFIG_PATH is derived from audit_loop_root in the orchestrator, so
    # point a scratch orchestrator dir at the scratch projects.yaml via a shim tree.
    shim = scratch / "loop"
    (shim / "orchestrator").mkdir(parents=True)
    for name in ("orchestrator.py", "make_audit_request.py"):
        shutil.copy2(LOOP_ROOT / "orchestrator" / name, shim / "orchestrator" / name)
    shutil.copy2(scratch / "projects.yaml", shim / "orchestrator" / "projects.yaml")
    shutil.copytree(LOOP_ROOT / "rulebook", shim / "rulebook")
    shutil.copytree(LOOP_ROOT / "checks", shim / "checks")
    config["paths"]["audit_loop_root"] = str(shim)
    config_path.write_text(yaml.safe_dump(config))

    # 1. Enqueue a science event for the clone's HEAD and run a pass.
    (state / "spool").mkdir()
    (state / "spool" / "evt-selftest.json").write_text(
        json.dumps({"type": "science_commit", "sha": science_head, "source": "selftest"}))
    venv_python = str(LOOP_ROOT / ".venv" / "bin" / "python")
    result = subprocess.run(
        [venv_python, str(shim / "orchestrator" / "orchestrator.py"),
         "--config", str(config_path), "--simulate-codex", "process"],
        capture_output=True, text=True, timeout=1800)
    print(result.stdout[-3000:])
    if result.returncode != 0:
        print(result.stderr[-3000:])
        print("SELFTEST FAIL: orchestrator pass errored")
        return 1

    controller_state = json.loads((state / "controller" / "state.json").read_text())
    cycles = controller_state.get("cycles", {})
    assert cycles, "no cycle created"
    cycle_id, cycle = next(iter(cycles.items()))
    assert cycle["status"] == "FINAL", f"cycle not FINAL: {cycle['status']}"
    assert cycle["science_commit"] == science_head
    pending = json.loads((state / "pending_reviews" / f"{cycle_id}.json").read_text())
    # The stub grades to the Tier-0 floors, so a tree with hard failures must
    # come back BLOCK with one finding per failing check.
    tier0 = json.loads((state / "cycles" / cycle_id / "check_report.json").read_text())
    hard = sorted(r["check_id"] for r in tier0["results"]
                  if r["class"] == "HARD" and r["status"] in {"FAIL", "ERROR"})
    assert pending["decision"] == ("BLOCK" if hard else "PASS_WITH_CAVEATS"), pending["decision"]
    assert len(pending["finding_ids"]) == max(1, len(hard)), pending["finding_ids"]
    audit_log = sh(["git", "log", "--oneline", "-2"], cwd=audit).stdout
    assert cycle_id in audit_log, "audit repo missing cycle commit"
    print(f"PASS: {cycle_id} FINAL, artifacts committed to audit repo, pending review emitted")

    # 2. Submit a disposition through the controller in-process.
    import os
    os.environ.update({
        "SCIENCE_REPO_PATH": str(science), "AUDIT_REPO_PATH": str(audit),
        "PROJECT_CONFIG_PATH": str(shim / "orchestrator" / "projects.yaml"),
        "CONTROLLER_STATE_PATH": str(state / "controller" / "state.json"),
    })
    for line in (state / "secrets.env").read_text().splitlines():
        k, _, v = line.partition("=")
        os.environ[k] = v
    sys.path.insert(0, str(PROJECT_ROOT / "science-audit-controller"))
    from app.main import create_app
    from fastapi.testclient import TestClient
    client = TestClient(create_app())
    disposition = {
        "cycle_id": cycle_id,
        "audit_report_id": cycle["audit_report_id"],
        "report_sha256_confirmed": True,
        "report_sha256": cycle["audit_report_sha256"],
        # One disposition per finding: the controller rejects partial answers,
        # which is the point of the per-finding rule.
        "findings": [{"finding_id": fid, "disposition": "PASS_NO_ACTION"}
                     for fid in pending["finding_ids"]],
    }
    response = client.post("/claude/dispositions", json=disposition,
                           headers={"Authorization": "Bearer selftest-claude_api_token"})
    body = response.json()
    assert response.status_code == 200 and body.get("valid"), f"disposition rejected: {body}"
    print("PASS: disposition recorded through controller")

    # 3. Escalation wiring: threshold=1 means the still-open finding escalates.
    result = subprocess.run(
        [venv_python, str(shim / "orchestrator" / "orchestrator.py"),
         "--config", str(config_path), "process"],
        capture_output=True, text=True, timeout=300)
    esc = json.loads((state / "escalations.json").read_text())
    assert esc["escalations"] and esc["escalations"][0]["finding_id"] == "F-001"
    print("PASS: escalation raised for unresolved finding (threshold=1)")

    # 4. Idempotency: re-delivering the same commit creates no second cycle.
    (state / "spool" / "evt-dup.json").write_text(
        json.dumps({"type": "science_commit", "sha": science_head, "source": "selftest-dup"}))
    subprocess.run(
        [venv_python, str(shim / "orchestrator" / "orchestrator.py"),
         "--config", str(config_path), "--simulate-codex", "process"],
        capture_output=True, text=True, timeout=600)
    controller_state = json.loads((state / "controller" / "state.json").read_text())
    assert len(controller_state["cycles"]) == 1, "duplicate cycle created"
    print("PASS: same-commit re-delivery is idempotent")

    print("SELFTEST OK — production repos and state untouched")
    shutil.rmtree(scratch, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
