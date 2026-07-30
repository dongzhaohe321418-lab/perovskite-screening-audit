from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.blocker_reducer import reduce_blockers
from app.models import Cycle
from app.storage import JsonStorage


EXPECTED_AUDIT_OUTPUT_FILES = [
    "audit_report.md",
    "audit_result.json",
    "codex_run_metadata.json",
    "report_manifest.json",
]


class CodexAdapter:
    """Stub adapter that stores generated audit prompts.

    TODO: Add a real Codex API/task integration behind this interface.
    """

    def __init__(self, storage: JsonStorage, prompt_dir: str | Path = "prompts"):
        self.storage = storage
        self.prompt_dir = Path(prompt_dir)

    def create_audit_task(self, cycle: Cycle, previous_findings: list[dict[str, Any]] | None = None) -> str:
        blocker_state = reduce_blockers(
            self.storage.event_log(),
            cycle.project_id,
            quarantined=self.storage.quarantined_event_hashes(cycle.project_id),
        )
        context = {
            "cycle_id": cycle.cycle_id,
            "project_id": cycle.project_id,
            "science_repo": cycle.science_repo,
            "fixed_science_commit_sha": cycle.science_commit,
            "evidence_manifest_sha256": cycle.evidence_manifest_sha256,
            "audit_request": cycle.audit_request,
            "previous_findings": previous_findings or [],
            "active_blockers": [
                event.model_dump(mode="json")
                for event in blocker_state.active.values()
            ],
            "open_findings": [
                event.model_dump(mode="json")
                for event in blocker_state.findings.values()
            ],
            "submitted_fix_commits": blocker_state.fix_commits,
            "reaudit_finding_ids": [
                finding_id
                for finding_id, reaudit_cycle in blocker_state.reaudit_cycles.items()
                if reaudit_cycle == cycle.cycle_id
            ],
            "allowed_actions": [
                "read science repository at the fixed commit",
                "write audit artifacts under the current cycle directory",
                "push raw audit artifacts to the audit repository branch audit",
            ],
            "forbidden_actions": [
                "modify the Science Repo",
                "modify policy, active blockers, event logs, Claude dispositions, PI approvals, or historical cycles",
                "write outside the current cycle directory",
                "claim a prior finding is closed without verifying its submitted fix commit in this cycle",
            ],
            "audit_repo_branch": "audit",
            "expected_output_files": EXPECTED_AUDIT_OUTPUT_FILES,
        }
        prompt = "\n\n".join(
            [
                self._read_template("codex_system.md"),
                self._read_template("codex_audit_task.md"),
                "## Machine-Generated Cycle Context\n\n```json\n"
                + json.dumps(context, indent=2, sort_keys=True)
                + "\n```",
            ]
        )
        self.storage.store_codex_task(cycle.cycle_id, prompt)
        return prompt

    def _read_template(self, name: str) -> str:
        return (self.prompt_dir / name).read_text(encoding="utf-8").strip()
