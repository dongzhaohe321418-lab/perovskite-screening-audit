from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

import jsonschema

from app.blocker_reducer import BlockerState, reduce_blockers
from app.claude_adapter import ClaudeAdapter
from app.github_client import GitHubClient
from app.json_utils import DuplicateJsonKeyError, strict_json_loads
from app.models import BlockerEvent, Cycle, CycleStatus, ValidationResult
from app.storage import (
    AuditHeadConflict,
    DuplicateDispositionError,
    ImmutableCycleError,
    JsonStorage,
)


ALLOWED_AUDIT_FILES = {
    "audit_request.json",
    "evidence_manifest.json",
    "audit_report.md",
    "audit_result.json",
    "codex_run_metadata.json",
    "report_manifest.json",
}
REQUIRED_AUDIT_FILES = {
    "audit_report.md",
    "audit_result.json",
    "codex_run_metadata.json",
    "report_manifest.json",
}
FORBIDDEN_FILENAMES = {
    "action_policy.yaml",
    "active_blockers.json",
    "event_log.jsonl",
    "claude_disposition.json",
    "pi_approval.json",
}
AUDIT_DECISIONS = {"PASS", "PASS_WITH_CAVEATS", "BLOCK", "NOT_VERIFIABLE"}


class ReportValidator:
    def __init__(
        self,
        storage: JsonStorage,
        github: GitHubClient,
        claude: ClaudeAdapter,
        schema_dir: str | Path = "schemas",
        initial_audit_heads: dict[str, str] | None = None,
    ):
        self.storage = storage
        self.github = github
        self.claude = claude
        self.schema_dir = Path(schema_dir)
        self.initial_audit_heads = initial_audit_heads or {}

    def validate_audit_push(
        self,
        project_id: str,
        before_sha: str | None,
        after_sha: str,
    ) -> ValidationResult:
        existing_head = self.storage.audit_head(project_id)
        expected_initial = self.initial_audit_heads.get(project_id, "0" * 40)
        if existing_head is None and before_sha != expected_initial:
            return ValidationResult(
                valid=False,
                errors=[
                    "first audit push does not start from the configured trusted audit commit"
                ],
            )
        comparison_base = self.storage.ensure_audit_head(project_id, expected_initial)
        if not self.github.is_ancestor("audit", comparison_base, after_sha):
            return ValidationResult(
                valid=False,
                errors=["audit branch update is not a fast-forward from the last trusted audit head"],
            )
        changed = self.github.list_changed_files("audit", comparison_base, after_sha)
        errors = self._validate_changed_paths(project_id, changed)
        cycle_id = self._cycle_id_from_paths(project_id, changed)
        if not cycle_id:
            errors.append("changed files must belong to exactly one cycle")
            return ValidationResult(valid=False, errors=errors)

        cycle = self.storage.get_cycle(cycle_id)
        if not cycle:
            errors.append(f"unknown cycle: {cycle_id}")
            return ValidationResult(valid=False, errors=errors)
        if cycle.project_id != project_id:
            errors.append("cycle project does not match audit repository project")
        if cycle.status == CycleStatus.FINAL:
            if cycle.audit_repo_commit == after_sha and not errors:
                self._ensure_claude_task(cycle)
                return ValidationResult(valid=True, errors=[])
            errors.append("FINAL cycle audit history is immutable")
            return ValidationResult(valid=False, errors=errors)
        if errors:
            self.storage.mark_audit_invalid(cycle_id)
            return ValidationResult(valid=False, errors=errors)

        prefix = f"projects/{project_id}/cycles/{cycle_id}/"
        files = self._load_audit_files(after_sha, prefix, errors)
        audit_result = self._parse_json_file(files, "audit_result.json", errors)
        manifest = self._parse_json_file(files, "report_manifest.json", errors)
        metadata = self._parse_json_file(files, "codex_run_metadata.json", errors)
        audit_report = files.get("audit_report.md", "")
        if not audit_report.strip():
            errors.append("audit_report.md must be present and non-empty")

        if audit_result is not None:
            errors.extend(self._validate_audit_result(cycle, audit_result))
        if manifest is not None:
            errors.extend(self._validate_manifest(cycle, files, manifest))
        if metadata is not None:
            errors.extend(self._validate_metadata(cycle, metadata))
        if audit_result is not None and audit_report:
            errors.extend(self._validate_markdown_consistency(audit_report, audit_result))
        if "audit_request.json" in files:
            errors.extend(self._validate_embedded_audit_request(cycle, files["audit_request.json"]))
        if "evidence_manifest.json" in files:
            errors.extend(
                self._validate_embedded_evidence_manifest(
                    cycle,
                    files["evidence_manifest.json"],
                )
            )

        blocker_state = reduce_blockers(
            self.storage.event_log(),
            project_id,
            quarantined=self.storage.quarantined_event_hashes(project_id),
        )
        if blocker_state.fail_closed:
            errors.append("blocker event state is inconsistent")
        if audit_result is not None and not blocker_state.fail_closed:
            errors.extend(self._validate_finding_lifecycle(cycle, audit_result, blocker_state))

        if errors:
            self.storage.mark_audit_invalid(cycle_id)
            return ValidationResult(valid=False, errors=errors)

        report_hash = hashlib.sha256(audit_report.encode("utf-8")).hexdigest()
        report_id = f"{cycle_id}:{report_hash[:12]}"
        events = self._finding_events(cycle, audit_result or {}, blocker_state)
        try:
            updated, _ = self.storage.finalize_cycle(
                cycle_id,
                audit_repo_commit=after_sha,
                audit_report_sha256=report_hash,
                audit_report_id=report_id,
                audit_result=audit_result or {},
                events=events,
                expected_audit_head=comparison_base,
            )
        except (AuditHeadConflict, ImmutableCycleError, RuntimeError) as exc:
            return ValidationResult(valid=False, errors=[str(exc)])
        self._ensure_claude_task(updated, audit_report, audit_result or {})
        return ValidationResult(valid=True, errors=[])

    def _ensure_claude_task(
        self,
        cycle: Cycle,
        audit_report: str | None = None,
        audit_result: dict[str, Any] | None = None,
    ) -> None:
        if audit_report is None:
            if not cycle.audit_repo_commit:
                raise RuntimeError("FINAL cycle is missing its audit repository commit")
            prefix = f"projects/{cycle.project_id}/cycles/{cycle.cycle_id}/"
            audit_report = self.github.get_file_at_commit(
                "audit",
                cycle.audit_repo_commit,
                prefix + "audit_report.md",
            )
        self.claude.create_review_task(cycle, audit_report, audit_result or cycle.audit_result or {})

    def _validate_changed_paths(self, project_id: str, changed: list[str]) -> list[str]:
        errors: list[str] = []
        prefix = f"projects/{project_id}/cycles/"
        if not changed:
            return ["audit push contains no file changes"]
        for path in changed:
            parts = PurePosixPath(path).parts
            if any(part in FORBIDDEN_FILENAMES for part in parts):
                errors.append(f"forbidden path changed: {path}")
            if not path.startswith(prefix):
                errors.append(f"unrelated project path changed: {path}")
                continue
            if len(parts) != 5:
                errors.append(f"changed path must be directly under a cycle directory: {path}")
                continue
            if parts[-1] not in ALLOWED_AUDIT_FILES:
                errors.append(f"unexpected audit artifact: {path}")
        return errors

    @staticmethod
    def _cycle_id_from_paths(project_id: str, changed: list[str]) -> str | None:
        prefix = f"projects/{project_id}/cycles/"
        cycle_ids = {
            PurePosixPath(path).parts[3]
            for path in changed
            if path.startswith(prefix) and len(PurePosixPath(path).parts) == 5
        }
        return next(iter(cycle_ids)) if len(cycle_ids) == 1 else None

    def _load_audit_files(
        self,
        after_sha: str,
        prefix: str,
        errors: list[str],
    ) -> dict[str, str]:
        files: dict[str, str] = {}
        for name in ALLOWED_AUDIT_FILES:
            try:
                files[name] = self.github.get_file_at_commit("audit", after_sha, prefix + name)
            except (FileNotFoundError, subprocess.CalledProcessError):
                if name in REQUIRED_AUDIT_FILES:
                    errors.append(f"missing {name}")
        return files

    @staticmethod
    def _parse_json_file(
        files: dict[str, str],
        name: str,
        errors: list[str],
    ) -> dict[str, Any] | None:
        if name not in files:
            return None
        try:
            value = strict_json_loads(files[name])
        except (json.JSONDecodeError, DuplicateJsonKeyError) as exc:
            errors.append(f"invalid JSON in {name}: {exc}")
            return None
        if not isinstance(value, dict):
            errors.append(f"{name} must contain a JSON object")
            return None
        return value

    def _validate_schema(self, value: dict[str, Any], name: str) -> list[str]:
        schema = json.loads((self.schema_dir / f"{name}.schema.json").read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(
            schema,
            format_checker=jsonschema.FormatChecker(),
        )
        return [
            f"{name} schema error at {self._json_path(error.path)}: {error.message}"
            for error in sorted(validator.iter_errors(value), key=lambda item: list(item.path))
        ]

    def _validate_audit_result(self, cycle: Cycle, audit_result: dict[str, Any]) -> list[str]:
        errors = self._validate_schema(audit_result, "audit_result")
        if errors:
            return errors
        if audit_result.get("cycle_id") != cycle.cycle_id:
            errors.append("audit_result cycle_id does not match expected cycle")
        if audit_result.get("audited_commit") != cycle.science_commit:
            errors.append("audit_result audited_commit does not match fixed science commit")
        decision = audit_result.get("decision")
        if decision not in AUDIT_DECISIONS:
            errors.append("audit_result decision is not allowed")
        findings = audit_result.get("findings", [])
        finding_ids = [finding.get("finding_id") for finding in findings]
        if len(finding_ids) != len(set(finding_ids)):
            errors.append("finding IDs must be unique")
        closures = audit_result.get("verified_closed_findings", [])
        closure_ids = [item.get("finding_id") for item in closures]
        if len(closure_ids) != len(set(closure_ids)):
            errors.append("verified closure finding IDs must be unique")
        overlap = set(finding_ids).intersection(closure_ids)
        if overlap:
            errors.append(f"findings cannot be both open and verified closed: {sorted(overlap)}")
        if decision == "BLOCK":
            if not findings:
                errors.append("BLOCK requires at least one finding")
            for finding in findings:
                if not finding.get("blocked_scopes"):
                    errors.append(f"BLOCK finding lacks blocked_scopes: {finding.get('finding_id')}")
        else:
            for finding in findings:
                if finding.get("blocked_scopes"):
                    errors.append(
                        f"only BLOCK findings may contain blocked_scopes: {finding.get('finding_id')}"
                    )
        return errors

    def _validate_manifest(
        self,
        cycle: Cycle,
        files: dict[str, str],
        manifest: dict[str, Any],
    ) -> list[str]:
        errors = self._validate_schema(manifest, "report_manifest")
        if errors:
            return errors
        if manifest.get("cycle_id") != cycle.cycle_id:
            errors.append("report_manifest cycle_id does not match expected cycle")
        entries = manifest.get("files", {})
        expected_names = set(files) - {"report_manifest.json"}
        if set(entries) != expected_names:
            errors.append(
                "report_manifest files must exactly match the audit artifacts other than report_manifest.json"
            )
            return errors
        for name in sorted(expected_names):
            entry = entries[name]
            expected_hash = entry.get("sha256") if isinstance(entry, dict) else entry
            actual_hash = hashlib.sha256(files[name].encode("utf-8")).hexdigest()
            if not isinstance(expected_hash, str) or expected_hash.lower() != actual_hash:
                errors.append(f"report_manifest hash mismatch for {name}")
        return errors

    def _validate_metadata(self, cycle: Cycle, metadata: dict[str, Any]) -> list[str]:
        errors = self._validate_schema(metadata, "codex_run_metadata")
        if errors:
            return errors
        if metadata.get("cycle_id") != cycle.cycle_id:
            errors.append("codex_run_metadata cycle_id does not match expected cycle")
        if metadata.get("audited_commit") != cycle.science_commit:
            errors.append("codex_run_metadata audited_commit does not match fixed science commit")
        return errors

    @staticmethod
    def _validate_markdown_consistency(
        report: str,
        audit_result: dict[str, Any],
    ) -> list[str]:
        match = re.search(r"(?im)^\s*decision\s*:\s*([A-Z_]+)\s*$", report)
        if not match:
            return ["audit_report.md must contain a machine-readable Decision line"]
        if match.group(1) != audit_result.get("decision"):
            return ["Markdown and JSON decisions are inconsistent"]
        return []

    @staticmethod
    def _validate_embedded_audit_request(cycle: Cycle, raw_request: str) -> list[str]:
        try:
            embedded = strict_json_loads(raw_request)
        except (json.JSONDecodeError, DuplicateJsonKeyError) as exc:
            return [f"invalid JSON in audit_request.json: {exc}"]
        if embedded != cycle.audit_request:
            return ["audit_request.json does not match the fixed Science Commit audit request"]
        return []

    @staticmethod
    def _validate_embedded_evidence_manifest(cycle: Cycle, raw_manifest: str) -> list[str]:
        try:
            manifest = strict_json_loads(raw_manifest)
        except (json.JSONDecodeError, DuplicateJsonKeyError) as exc:
            return [f"invalid JSON in evidence_manifest.json: {exc}"]
        if not isinstance(manifest, dict):
            return ["evidence_manifest.json must contain a JSON object"]
        canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        actual_hash = hashlib.sha256(canonical).hexdigest()
        if actual_hash != cycle.evidence_manifest_sha256.lower():
            return ["evidence_manifest.json does not match evidence_manifest_sha256"]
        return []

    def _validate_finding_lifecycle(
        self,
        cycle: Cycle,
        audit_result: dict[str, Any],
        state: BlockerState,
    ) -> list[str]:
        errors: list[str] = []
        all_opened_ids = {
            event.finding_id
            for event in self.storage.event_log()
            if event.project_id == cycle.project_id and event.event == "FINDING_OPENED"
        }
        blocking = audit_result.get("decision") == "BLOCK"
        for finding in audit_result.get("findings", []):
            finding_id = finding["finding_id"]
            if finding_id in all_opened_ids and finding_id not in state.findings:
                errors.append(f"closed finding ID cannot be reused: {finding_id}")
            existing = state.findings.get(finding_id)
            if existing and bool(existing.data.get("blocking", True)) != blocking:
                errors.append(f"existing finding cannot change blocking class: {finding_id}")

        for closure in audit_result.get("verified_closed_findings", []):
            finding_id = closure["finding_id"]
            if finding_id not in state.findings:
                errors.append(f"cannot close unknown or inactive finding: {finding_id}")
                continue
            if state.fix_commits.get(finding_id) != cycle.science_commit:
                errors.append(f"verified closure lacks matching submitted fix commit: {finding_id}")
            if state.reaudit_cycles.get(finding_id) != cycle.cycle_id:
                errors.append(f"verified closure was not audited in this cycle: {finding_id}")
        return errors

    @staticmethod
    def _finding_events(
        cycle: Cycle,
        audit_result: dict[str, Any],
        state: BlockerState,
    ) -> list[BlockerEvent]:
        events: list[BlockerEvent] = []
        blocking = audit_result.get("decision") == "BLOCK"
        for finding in audit_result.get("findings", []):
            finding_id = finding["finding_id"]
            if finding_id in state.findings:
                continue
            events.append(
                BlockerEvent(
                    event="FINDING_OPENED",
                    finding_id=finding_id,
                    project_id=cycle.project_id,
                    cycle_id=cycle.cycle_id,
                    blocked_scopes=finding.get("blocked_scopes", []),
                    data={"blocking": blocking, "finding": finding},
                )
            )
        for closure in audit_result.get("verified_closed_findings", []):
            events.append(
                BlockerEvent(
                    event="FINDING_VERIFIED_CLOSED",
                    finding_id=closure["finding_id"],
                    project_id=cycle.project_id,
                    cycle_id=cycle.cycle_id,
                    data={
                        "verified_commit": cycle.science_commit,
                        "verification_summary": closure["verification_summary"],
                    },
                )
            )
        return events

    @staticmethod
    def _json_path(path: Any) -> str:
        parts = list(path)
        return "$" if not parts else "$." + ".".join(str(part) for part in parts)


class ClaudeDispositionValidator:
    ALLOWED_DISPOSITIONS = {
        "ACCEPT_AND_FIX",
        "ACCEPT_AND_STOP",
        "DISAGREE_WITH_EVIDENCE",
        "NEED_PI_DECISION",
        "DEFER_WITH_CAVEAT",
        "PASS_NO_ACTION",
    }

    def __init__(
        self,
        storage: JsonStorage,
        github: GitHubClient,
        schema_dir: str | Path = "schemas",
    ):
        self.storage = storage
        self.github = github
        self.schema_dir = Path(schema_dir)

    def validate(self, disposition: dict[str, Any]) -> ValidationResult:
        errors = self._validate_schema(disposition)
        cycle_id = disposition.get("cycle_id")
        cycle = self.storage.get_cycle(cycle_id) if isinstance(cycle_id, str) else None
        if errors:
            if cycle:
                self.storage.mark_disposition_invalid(cycle.cycle_id)
            return ValidationResult(valid=False, errors=errors)
        if not cycle or cycle.status != CycleStatus.FINAL:
            return ValidationResult(valid=False, errors=["unknown or non-FINAL cycle"])
        if self.storage.get_disposition(cycle.cycle_id):
            return ValidationResult(valid=False, errors=["disposition already recorded for cycle"])
        if disposition.get("audit_report_id") != cycle.audit_report_id:
            errors.append("audit report ID does not match")
        if disposition.get("report_sha256_confirmed") is not True:
            errors.append("report SHA confirmation must be true")
        if disposition.get("report_sha256", "").lower() != cycle.audit_report_sha256:
            errors.append("confirmed report SHA-256 does not match the FINAL report")

        expected = {
            finding["finding_id"]
            for finding in (cycle.audit_result or {}).get("findings", [])
        }
        provided_items = disposition.get("findings", [])
        provided_ids = [item["finding_id"] for item in provided_items]
        if len(provided_ids) != len(set(provided_ids)):
            errors.append("duplicate finding dispositions are not allowed")
        provided = set(provided_ids)
        missing = expected - provided
        unknown = provided - expected
        if missing:
            errors.append(f"missing finding dispositions: {sorted(missing)}")
        if unknown:
            errors.append(f"unknown finding IDs: {sorted(unknown)}")

        for item in provided_items:
            finding_id = item["finding_id"]
            if item.get("disposition") not in self.ALLOWED_DISPOSITIONS:
                errors.append(f"disallowed disposition: {item.get('disposition')}")
            if item.get("closed") is True:
                errors.append(f"Claude cannot directly close findings: {finding_id}")
            if item.get("disposition") == "ACCEPT_AND_FIX":
                fix_commit = item.get("fix_commit")
                if not fix_commit:
                    errors.append(f"ACCEPT_AND_FIX requires fix_commit for {finding_id}")
                elif fix_commit == cycle.science_commit:
                    errors.append(f"fix_commit must be newer than the audited commit for {finding_id}")
                elif not self.github.commit_exists("science", fix_commit):
                    errors.append(f"fix_commit does not exist in the Science Repo for {finding_id}")
                elif not self.github.is_ancestor("science", cycle.science_commit, fix_commit):
                    errors.append(
                        f"fix_commit does not descend from the audited commit for {finding_id}"
                    )
            elif item.get("fix_commit"):
                errors.append(f"fix_commit is only allowed with ACCEPT_AND_FIX for {finding_id}")

        if errors:
            self.storage.mark_disposition_invalid(cycle.cycle_id)
            return ValidationResult(valid=False, errors=errors)

        events: list[BlockerEvent] = []
        blocker_state = reduce_blockers(
            self.storage.event_log(),
            cycle.project_id,
            quarantined=self.storage.quarantined_event_hashes(cycle.project_id),
        )
        if blocker_state.fail_closed:
            self.storage.mark_disposition_invalid(cycle.cycle_id)
            return ValidationResult(valid=False, errors=["blocker event state is inconsistent"])
        for item in provided_items:
            finding_id = item["finding_id"]
            if finding_id not in blocker_state.findings:
                errors.append(f"finding is no longer active: {finding_id}")
                continue
            events.append(
                BlockerEvent(
                    event="DISPOSITION_RECORDED",
                    finding_id=finding_id,
                    project_id=cycle.project_id,
                    cycle_id=cycle.cycle_id,
                    data={"disposition": item["disposition"]},
                )
            )
            if item.get("fix_commit"):
                events.append(
                    BlockerEvent(
                        event="FIX_COMMIT_SUBMITTED",
                        finding_id=finding_id,
                        project_id=cycle.project_id,
                        cycle_id=cycle.cycle_id,
                        data={"fix_commit": item["fix_commit"]},
                    )
                )
                reaudit = self.storage.open_cycle_for_commit(
                    cycle.project_id, item["fix_commit"]
                )
                if reaudit:
                    events.append(
                        BlockerEvent(
                            event="REAUDIT_STARTED",
                            finding_id=finding_id,
                            project_id=cycle.project_id,
                            cycle_id=reaudit.cycle_id,
                            data={"fix_commit": item["fix_commit"]},
                        )
                    )
        if errors:
            self.storage.mark_disposition_invalid(cycle.cycle_id)
            return ValidationResult(valid=False, errors=errors)
        try:
            self.storage.record_disposition(cycle.cycle_id, disposition, events)
        except DuplicateDispositionError:
            return ValidationResult(valid=False, errors=["disposition already recorded for cycle"])
        return ValidationResult(valid=True, errors=[])

    def _validate_schema(self, disposition: dict[str, Any]) -> list[str]:
        schema = json.loads(
            (self.schema_dir / "claude_disposition.schema.json").read_text(encoding="utf-8")
        )
        validator = jsonschema.Draft202012Validator(
            schema,
            format_checker=jsonschema.FormatChecker(),
        )
        return [
            f"claude_disposition schema error: {error.message}"
            for error in sorted(validator.iter_errors(disposition), key=lambda item: list(item.path))
        ]
