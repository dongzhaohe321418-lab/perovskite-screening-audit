from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.blocker_reducer import reduce_blockers
from app.models import Cycle
from app.storage import JsonStorage


class ClaudeAdapter:
    """Stub adapter that stores generated Claude disposition prompts.

    TODO: Add a real Anthropic/Claude task integration behind this interface.
    """

    def __init__(self, storage: JsonStorage, prompt_dir: str | Path = "prompts"):
        self.storage = storage
        self.prompt_dir = Path(prompt_dir)

    def create_review_task(self, cycle: Cycle, audit_report_text: str, audit_result: dict[str, Any]) -> str:
        findings = audit_result.get("findings", [])
        context = {
            "cycle_id": cycle.cycle_id,
            "audit_report_id": cycle.audit_report_id,
            "science_commit_sha": cycle.science_commit,
            "audit_repo_commit_sha": cycle.audit_repo_commit,
            "audit_report_sha256": cycle.audit_report_sha256,
            "full_audit_report_text": audit_report_text,
            "full_audit_result_json": audit_result,
            "all_finding_ids": [finding.get("finding_id") for finding in findings],
            "current_active_blockers": [
                event.model_dump(mode="json")
                for event in reduce_blockers(self.storage.event_log(), cycle.project_id).active.values()
            ],
            "previous_dispositions": self.storage.get_disposition(cycle.cycle_id),
            "allowed_actions": [
                "respond with one disposition per finding",
                "provide evidence for disagreement",
                "provide a new full Science Commit SHA when claiming a fix",
            ],
            "forbidden_actions": [
                "mark a finding as closed",
                "reply all fixed without per-finding dispositions",
                "change policy, blockers, event logs, PI approval, or audit history",
            ],
        }
        prompt = "\n\n".join(
            [
                (self.prompt_dir / "claude_disposition.md").read_text(encoding="utf-8").strip(),
                "## Machine-Generated Review Context\n\n```json\n"
                + json.dumps(context, indent=2, sort_keys=True)
                + "\n```",
            ]
        )
        self.storage.store_claude_task(cycle.cycle_id, prompt)
        return prompt
