from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

import jsonschema

from app.blocker_reducer import reduce_blockers
from app.codex_adapter import CodexAdapter
from app.github_client import GitHubClient
from app.json_utils import DuplicateJsonKeyError, strict_json_loads
from app.models import BlockerEvent, Cycle, CycleStatus
from app.storage import JsonStorage


TRIGGER_TYPE = "NEW_SCIENCE_COMMIT"


class CycleManager:
    def __init__(
        self,
        storage: JsonStorage,
        github: GitHubClient,
        codex: CodexAdapter,
        schema_dir: str | Path = "schemas",
    ):
        self.storage = storage
        self.github = github
        self.codex = codex
        self.schema_dir = Path(schema_dir)

    def handle_science_push(self, project_id: str, science_repo: str, science_commit: str) -> Cycle:
        audit_request, raw_request, request_error = self._load_audit_request(science_commit)
        evidence_hash = self._evidence_manifest_hash(audit_request, raw_request)
        idempotency_key = hashlib.sha256(
            f"{project_id}{science_commit}{TRIGGER_TYPE}{evidence_hash}".encode("utf-8")
        ).hexdigest()
        cycle, created = self.storage.create_or_get_cycle(
            {
                "project_id": project_id,
                "science_repo": science_repo,
                "science_commit": science_commit,
                "trigger_type": TRIGGER_TYPE,
                "evidence_manifest_sha256": evidence_hash,
                "idempotency_key": idempotency_key,
            }
        )
        if not created and cycle.status in {
            CycleStatus.AUDIT_REQUEST_INVALID,
            CycleStatus.CODEX_TASK_CREATED,
            CycleStatus.AUDIT_OUTPUT_INVALID,
            CycleStatus.FINAL,
        }:
            return cycle
        if (
            request_error
            or not audit_request
            or not self._validate_audit_request(
                project_id,
                science_commit,
                audit_request,
            )
        ):
            return self.storage.update_cycle(cycle.cycle_id, status=CycleStatus.AUDIT_REQUEST_INVALID)

        if cycle.audit_request is None:
            cycle = self.storage.update_cycle(
                cycle.cycle_id,
                audit_request=audit_request,
                status=CycleStatus.CREATED,
            )
        self._record_reaudit_events(cycle)
        self.codex.create_audit_task(cycle, previous_findings=self._previous_findings(project_id))
        return self.storage.update_cycle(cycle.cycle_id, status=CycleStatus.CODEX_TASK_CREATED)

    def _load_audit_request(self, science_commit: str) -> tuple[dict[str, Any] | None, str, str | None]:
        try:
            raw = self.github.get_file_at_commit("science", science_commit, ".audit/audit_request.json")
            value = strict_json_loads(raw)
            if not isinstance(value, dict):
                return None, raw, "audit request must be a JSON object"
            return value, raw, None
        except (
            FileNotFoundError,
            subprocess.CalledProcessError,
            json.JSONDecodeError,
            DuplicateJsonKeyError,
            UnicodeDecodeError,
        ) as exc:
            return None, "", str(exc)

    def _validate_audit_request(
        self,
        project_id: str,
        science_commit: str,
        audit_request: dict[str, Any],
    ) -> bool:
        schema = json.loads((self.schema_dir / "audit_request.schema.json").read_text(encoding="utf-8"))
        try:
            jsonschema.validate(audit_request, schema)
            if audit_request.get("project_id") != project_id:
                return False
            manifest = audit_request.get("evidence_manifest")
            supplied_hash = audit_request.get("evidence_manifest_sha256")
            if manifest is not None:
                canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
                return hashlib.sha256(canonical).hexdigest() == supplied_hash.lower()
            manifest_path = audit_request.get("evidence_manifest_path")
            if manifest_path is not None:
                path = PurePosixPath(manifest_path)
                if path.is_absolute() or ".." in path.parts or path.parts[0] != ".audit":
                    return False
                raw_manifest = self.github.get_file_at_commit(
                    "science",
                    science_commit,
                    manifest_path,
                )
                parsed_manifest = strict_json_loads(raw_manifest)
                if not isinstance(parsed_manifest, dict):
                    return False
                canonical = json.dumps(
                    parsed_manifest,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                return hashlib.sha256(canonical).hexdigest() == supplied_hash.lower()
            return True
        except (
            FileNotFoundError,
            subprocess.CalledProcessError,
            json.JSONDecodeError,
            DuplicateJsonKeyError,
            UnicodeDecodeError,
            jsonschema.ValidationError,
        ):
            return False

    @staticmethod
    def _evidence_manifest_hash(audit_request: dict[str, Any] | None, raw_request: str) -> str:
        if audit_request:
            supplied = audit_request.get("evidence_manifest_sha256")
            if isinstance(supplied, str) and len(supplied) == 64:
                return supplied
            if "evidence_manifest" in audit_request:
                canonical = json.dumps(
                    audit_request["evidence_manifest"],
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                return hashlib.sha256(canonical).hexdigest()
        return hashlib.sha256(raw_request.encode("utf-8")).hexdigest()

    def _previous_findings(self, project_id: str) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        for cycle in self.storage.list_cycles(project_id):
            if cycle.audit_result:
                findings.extend(cycle.audit_result.get("findings", []))
        return findings

    def _record_reaudit_events(self, cycle: Cycle) -> None:
        state = reduce_blockers(
            self.storage.event_log(),
            cycle.project_id,
            quarantined=self.storage.quarantined_event_hashes(cycle.project_id),
        )
        if state.fail_closed:
            return
        events = [
            BlockerEvent(
                event="REAUDIT_STARTED",
                finding_id=finding_id,
                project_id=cycle.project_id,
                cycle_id=cycle.cycle_id,
                data={"fix_commit": fix_commit},
            )
            for finding_id, fix_commit in state.fix_commits.items()
            if fix_commit == cycle.science_commit
        ]
        self.storage.append_events(events)
