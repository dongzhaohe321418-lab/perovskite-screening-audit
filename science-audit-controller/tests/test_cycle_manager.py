from __future__ import annotations

import hashlib
import json

import pytest

from app.claude_adapter import ClaudeAdapter
from app.codex_adapter import CodexAdapter
from app.cycle_manager import CycleManager
from app.report_validator import ReportValidator
from app.storage import ImmutableCycleError, JsonStorage

from tests.utils import ROOT, FakeGitHub, audit_artifacts, valid_audit_request


SCIENCE_SHA = "d" * 40


def make_cycle(tmp_path, science_sha: str = SCIENCE_SHA, storage=None, fake=None):
    storage = storage or JsonStorage(tmp_path / "state.json")
    fake = fake or FakeGitHub()
    fake.files[("science", science_sha, ".audit/audit_request.json")] = json.dumps(
        valid_audit_request()
    )
    fake.existing_commits.add(science_sha)
    codex = CodexAdapter(storage, ROOT / "prompts")
    manager = CycleManager(storage, fake, codex, ROOT / "schemas")
    cycle = manager.handle_science_push(
        "perovskite-screening",
        "perovskite-screening",
        science_sha,
    )
    claude = ClaudeAdapter(storage, ROOT / "prompts")
    validator = ReportValidator(storage, fake, claude, ROOT / "schemas")
    return storage, fake, cycle, validator


def validate_artifacts(fake, validator, cycle, before, after, decision="PASS", findings=None, closures=None):
    paths = audit_artifacts(
        fake,
        after,
        cycle,
        decision=decision,
        findings=findings or [],
        verified_closed_findings=closures,
    )
    fake.set_diff("audit", before, after, paths)
    return validator.validate_audit_push("perovskite-screening", before, after)


def test_invalid_audit_request_project_is_rejected(tmp_path):
    storage = JsonStorage(tmp_path / "state.json")
    fake = FakeGitHub()
    fake.files[("science", SCIENCE_SHA, ".audit/audit_request.json")] = json.dumps(
        {
            "project_id": "wrong-project",
            "audit_scope": "scope",
            "evidence_manifest_sha256": "a" * 64,
        }
    )
    manager = CycleManager(
        storage,
        fake,
        CodexAdapter(storage, ROOT / "prompts"),
        ROOT / "schemas",
    )

    cycle = manager.handle_science_push("perovskite-screening", "perovskite-screening", SCIENCE_SHA)

    assert cycle.status.value == "AUDIT_REQUEST_INVALID"


def test_inline_evidence_manifest_hash_must_match(tmp_path):
    storage = JsonStorage(tmp_path / "state.json")
    fake = FakeGitHub()
    request = valid_audit_request()
    request["evidence_manifest"] = {"files": ["result.json"]}
    request["evidence_manifest_sha256"] = "0" * 64
    fake.files[("science", SCIENCE_SHA, ".audit/audit_request.json")] = json.dumps(request)
    manager = CycleManager(
        storage,
        fake,
        CodexAdapter(storage, ROOT / "prompts"),
        ROOT / "schemas",
    )

    cycle = manager.handle_science_push("perovskite-screening", "perovskite-screening", SCIENCE_SHA)

    assert cycle.status.value == "AUDIT_REQUEST_INVALID"


def test_evidence_manifest_path_is_loaded_from_fixed_commit(tmp_path):
    storage = JsonStorage(tmp_path / "state.json")
    fake = FakeGitHub()
    manifest = {"file_count": 1, "tree_sha256": "b" * 64}
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    request = valid_audit_request()
    request["evidence_manifest_path"] = ".audit/evidence_manifest.json"
    request["evidence_manifest_sha256"] = hashlib.sha256(canonical).hexdigest()
    fake.files[("science", SCIENCE_SHA, ".audit/audit_request.json")] = json.dumps(request)
    fake.files[("science", SCIENCE_SHA, ".audit/evidence_manifest.json")] = json.dumps(
        manifest,
        indent=2,
    )
    manager = CycleManager(
        storage,
        fake,
        CodexAdapter(storage, ROOT / "prompts"),
        ROOT / "schemas",
    )

    cycle = manager.handle_science_push(
        "perovskite-screening",
        "perovskite-screening",
        SCIENCE_SHA,
    )

    assert cycle.status.value == "CODEX_TASK_CREATED"
    assert cycle.evidence_manifest_sha256 == request["evidence_manifest_sha256"]


def test_evidence_manifest_path_hash_mismatch_is_rejected(tmp_path):
    storage = JsonStorage(tmp_path / "state.json")
    fake = FakeGitHub()
    request = valid_audit_request()
    request["evidence_manifest_path"] = ".audit/evidence_manifest.json"
    fake.files[("science", SCIENCE_SHA, ".audit/audit_request.json")] = json.dumps(request)
    fake.files[("science", SCIENCE_SHA, ".audit/evidence_manifest.json")] = json.dumps(
        {"file_count": 1}
    )
    manager = CycleManager(
        storage,
        fake,
        CodexAdapter(storage, ROOT / "prompts"),
        ROOT / "schemas",
    )

    cycle = manager.handle_science_push(
        "perovskite-screening",
        "perovskite-screening",
        SCIENCE_SHA,
    )

    assert cycle.status.value == "AUDIT_REQUEST_INVALID"


def test_partially_created_cycle_is_resumed_idempotently(tmp_path):
    storage = JsonStorage(tmp_path / "state.json")
    fake = FakeGitHub()
    raw_request = json.dumps(valid_audit_request())
    fake.files[("science", SCIENCE_SHA, ".audit/audit_request.json")] = raw_request
    evidence_hash = "a" * 64
    idempotency_key = hashlib.sha256(
        (
            "perovskite-screening"
            + SCIENCE_SHA
            + "NEW_SCIENCE_COMMIT"
            + evidence_hash
        ).encode("utf-8")
    ).hexdigest()
    partial, created = storage.create_or_get_cycle(
        {
            "project_id": "perovskite-screening",
            "science_repo": "perovskite-screening",
            "science_commit": SCIENCE_SHA,
            "trigger_type": "NEW_SCIENCE_COMMIT",
            "evidence_manifest_sha256": evidence_hash,
            "idempotency_key": idempotency_key,
        }
    )
    assert created
    assert partial.status.value == "CREATED"
    manager = CycleManager(
        storage,
        fake,
        CodexAdapter(storage, ROOT / "prompts"),
        ROOT / "schemas",
    )

    resumed = manager.handle_science_push(
        "perovskite-screening",
        "perovskite-screening",
        SCIENCE_SHA,
    )

    assert resumed.cycle_id == partial.cycle_id
    assert resumed.status.value == "CODEX_TASK_CREATED"
    assert resumed.audit_request == valid_audit_request()


def test_codex_audit_commit_with_forbidden_path_is_rejected(tmp_path):
    storage, fake, cycle, validator = make_cycle(tmp_path)
    before, after = "0" * 40, "e" * 40
    paths = audit_artifacts(fake, after, cycle, decision="PASS", findings=[])
    paths.append("projects/perovskite-screening/action_policy.yaml")
    fake.set_diff("audit", before, after, paths)

    result = validator.validate_audit_push("perovskite-screening", before, after)

    assert not result.valid
    assert any("forbidden path" in error for error in result.errors)
    assert storage.get_cycle(cycle.cycle_id).status.value == "AUDIT_OUTPUT_INVALID"


def test_codex_audit_commit_with_invalid_schema_is_rejected(tmp_path):
    _, fake, cycle, validator = make_cycle(tmp_path)
    before, after = "0" * 40, "f" * 40
    paths = audit_artifacts(fake, after, cycle, decision="PASS", findings=[])
    prefix = f"projects/perovskite-screening/cycles/{cycle.cycle_id}/"
    fake.files[("audit", after, prefix + "audit_result.json")] = json.dumps(
        {"cycle_id": cycle.cycle_id}
    )
    fake.set_diff("audit", before, after, paths)

    result = validator.validate_audit_push("perovskite-screening", before, after)

    assert not result.valid
    assert any("audit_result schema error" in error for error in result.errors)


def test_duplicate_json_keys_in_audit_result_are_rejected(tmp_path):
    _, fake, cycle, validator = make_cycle(tmp_path)
    before, after = "0" * 40, "f" * 40
    paths = audit_artifacts(fake, after, cycle, decision="PASS", findings=[])
    prefix = f"projects/perovskite-screening/cycles/{cycle.cycle_id}/"
    fake.files[("audit", after, prefix + "audit_result.json")] = (
        '{"cycle_id":"'
        + cycle.cycle_id
        + '","cycle_id":"CYCLE-999999","audited_commit":"'
        + cycle.science_commit
        + '","decision":"PASS","findings":[]}'
    )
    fake.set_diff("audit", before, after, paths)

    result = validator.validate_audit_push("perovskite-screening", before, after)

    assert not result.valid
    assert any("duplicate JSON key" in error for error in result.errors)


def test_block_without_blocked_scopes_is_rejected(tmp_path):
    _, fake, cycle, validator = make_cycle(tmp_path)
    before, after = "0" * 40, "1" * 40

    result = validate_artifacts(
        fake,
        validator,
        cycle,
        before,
        after,
        decision="BLOCK",
        findings=[
            {
                "finding_id": "F-001",
                "title": "Issue",
                "severity": "HIGH",
                "status": "OPEN",
            }
        ],
    )

    assert not result.valid
    assert any("blocked_scopes" in error for error in result.errors)


def test_missing_required_artifacts_cannot_finalize(tmp_path):
    storage, fake, cycle, validator = make_cycle(tmp_path)
    before, after = "0" * 40, "2" * 40
    paths = audit_artifacts(fake, after, cycle, decision="PASS", findings=[])
    prefix = f"projects/perovskite-screening/cycles/{cycle.cycle_id}/"
    del fake.files[("audit", after, prefix + "audit_report.md")]
    del fake.files[("audit", after, prefix + "codex_run_metadata.json")]
    fake.set_diff("audit", before, after, paths)

    result = validator.validate_audit_push("perovskite-screening", before, after)

    assert not result.valid
    assert "missing audit_report.md" in result.errors
    assert "missing codex_run_metadata.json" in result.errors
    assert storage.get_cycle(cycle.cycle_id).status.value != "FINAL"


def test_report_manifest_is_schema_validated_and_complete(tmp_path):
    _, fake, cycle, validator = make_cycle(tmp_path)
    before, after = "0" * 40, "2" * 40
    paths = audit_artifacts(fake, after, cycle, decision="PASS", findings=[])
    prefix = f"projects/perovskite-screening/cycles/{cycle.cycle_id}/"
    fake.files[("audit", after, prefix + "report_manifest.json")] = json.dumps(
        {"cycle_id": cycle.cycle_id, "files": {}}
    )
    fake.set_diff("audit", before, after, paths)

    result = validator.validate_audit_push("perovskite-screening", before, after)

    assert not result.valid
    assert any("report_manifest schema error" in error for error in result.errors)


def test_valid_codex_audit_commit_marks_cycle_final(tmp_path):
    storage, fake, cycle, validator = make_cycle(tmp_path)
    before, after = "0" * 40, "2" * 40

    result = validate_artifacts(fake, validator, cycle, before, after)

    updated = storage.get_cycle(cycle.cycle_id)
    assert result.valid
    assert updated.status.value == "FINAL"
    assert updated.audit_repo_commit == after
    assert updated.audit_report_sha256 != hashlib.sha256(b"").hexdigest()
    assert updated.audit_report_id is not None


def test_final_audit_history_cannot_be_overwritten(tmp_path):
    storage, fake, cycle, validator = make_cycle(tmp_path)
    first_before, first_after = "0" * 40, "2" * 40
    assert validate_artifacts(fake, validator, cycle, first_before, first_after).valid
    original = storage.get_cycle(cycle.cycle_id)

    second_after = "3" * 40
    paths = audit_artifacts(
        fake,
        second_after,
        cycle,
        decision="BLOCK",
        findings=[
            {
                "finding_id": "F-NEW",
                "title": "New",
                "severity": "HIGH",
                "status": "OPEN",
                "blocked_scopes": ["production"],
            }
        ],
    )
    fake.set_diff("audit", first_after, second_after, paths)

    result = validator.validate_audit_push(
        "perovskite-screening",
        first_after,
        second_after,
    )

    current = storage.get_cycle(cycle.cycle_id)
    assert not result.valid
    assert any("immutable" in error for error in result.errors)
    assert current.audit_repo_commit == original.audit_repo_commit
    assert current.audit_result == original.audit_result
    assert current.status.value == "FINAL"


def test_invalid_audit_request_cycle_cannot_be_finalized(tmp_path):
    storage = JsonStorage(tmp_path / "state.json")
    fake = FakeGitHub()
    fake.files[("science", SCIENCE_SHA, ".audit/audit_request.json")] = json.dumps(
        {"project_id": "perovskite-screening"}
    )
    manager = CycleManager(
        storage,
        fake,
        CodexAdapter(storage, ROOT / "prompts"),
        ROOT / "schemas",
    )
    cycle = manager.handle_science_push(
        "perovskite-screening",
        "perovskite-screening",
        SCIENCE_SHA,
    )
    validator = ReportValidator(
        storage,
        fake,
        ClaudeAdapter(storage, ROOT / "prompts"),
        ROOT / "schemas",
    )
    before, after = "0" * 40, "a" * 40
    paths = audit_artifacts(fake, after, cycle, decision="PASS", findings=[])
    fake.set_diff("audit", before, after, paths)

    result = validator.validate_audit_push("perovskite-screening", before, after)

    assert not result.valid
    assert any("not eligible" in error for error in result.errors)
    assert storage.get_cycle(cycle.cycle_id).status.value == "AUDIT_REQUEST_INVALID"


def test_rejected_audit_change_remains_in_comparison_until_reverted(tmp_path):
    storage, fake, cycle, validator = make_cycle(tmp_path)
    trusted = "0" * 40
    bad_commit = "a" * 40
    bad_paths = audit_artifacts(fake, bad_commit, cycle, decision="PASS", findings=[])
    forbidden = "projects/perovskite-screening/event_log.jsonl"
    fake.set_diff("audit", trusted, bad_commit, bad_paths + [forbidden])
    assert not validator.validate_audit_push(
        "perovskite-screening",
        trusted,
        bad_commit,
    ).valid
    assert storage.audit_head(cycle.project_id) == trusted

    descendant = "b" * 40
    descendant_paths = audit_artifacts(fake, descendant, cycle, decision="PASS", findings=[])
    fake.set_diff("audit", trusted, descendant, descendant_paths + [forbidden])

    result = validator.validate_audit_push(
        "perovskite-screening",
        bad_commit,
        descendant,
    )

    assert not result.valid
    assert any("forbidden path" in error for error in result.errors)
    assert storage.audit_head(cycle.project_id) == trusted


def test_non_fast_forward_audit_update_is_rejected(tmp_path):
    storage, fake, cycle, validator = make_cycle(tmp_path)
    trusted, after = "0" * 40, "a" * 40
    paths = audit_artifacts(fake, after, cycle, decision="PASS", findings=[])
    fake.set_diff("audit", trusted, after, paths)
    fake.ancestor_results[("audit", trusted, after)] = False

    result = validator.validate_audit_push("perovskite-screening", trusted, after)

    assert not result.valid
    assert result.errors == [
        "audit branch update is not a fast-forward from the last trusted audit head"
    ]
    assert storage.get_cycle(cycle.cycle_id).status.value != "FINAL"


def test_first_audit_push_must_match_configured_trusted_head(tmp_path):
    storage, fake, cycle, _ = make_cycle(tmp_path)
    trusted = "a" * 40
    after = "b" * 40
    validator = ReportValidator(
        storage,
        fake,
        ClaudeAdapter(storage, ROOT / "prompts"),
        ROOT / "schemas",
        {"perovskite-screening": trusted},
    )
    paths = audit_artifacts(fake, after, cycle, decision="PASS", findings=[])
    fake.set_diff("audit", "0" * 40, after, paths)

    result = validator.validate_audit_push(
        "perovskite-screening",
        "0" * 40,
        after,
    )

    assert not result.valid
    assert result.errors == [
        "first audit push does not start from the configured trusted audit commit"
    ]


def test_finalized_cycles_form_an_unforgeable_receipt_chain(tmp_path):
    """Each receipt names exactly one predecessor, computed by the controller."""
    storage, fake, first, validator = make_cycle(tmp_path)
    result = validate_artifacts(fake, validator, first, "0" * 40, "3" * 40,
                                decision="PASS", findings=[])
    assert result.valid, result.errors
    first_final = storage.get_cycle(first.cycle_id)
    assert first_final.parent_report_sha256 is None

    second_commit = "7" * 40
    fake.files[("science", second_commit, ".audit/audit_request.json")] = json.dumps(
        valid_audit_request()
    )
    codex = CodexAdapter(storage, ROOT / "prompts")
    manager = CycleManager(storage, fake, codex, ROOT / "schemas")
    second = manager.handle_science_push(first.project_id, first.science_repo, second_commit)
    result = validate_artifacts(fake, validator, second, "3" * 40, "4" * 40,
                               decision="PASS", findings=[])
    assert result.valid, result.errors

    second_final = storage.get_cycle(second.cycle_id)
    assert second_final.parent_report_sha256 == first_final.audit_report_sha256
    # The chain is a property of the receipts, not of their bodies: these two
    # fixtures share report text, so the hashes coincide while the link is real.
    assert second_final.audit_repo_commit != first_final.audit_repo_commit
    assert second_final.cycle_id > first_final.cycle_id


def test_parent_report_hash_is_immutable_once_final(tmp_path):
    storage, fake, cycle, validator = make_cycle(tmp_path)
    assert validate_artifacts(fake, validator, cycle, "0" * 40, "3" * 40,
                              decision="PASS", findings=[]).valid
    with pytest.raises(ImmutableCycleError):
        storage.update_cycle(cycle.cycle_id, parent_report_sha256="9" * 64)


def test_audit_result_without_coverage_is_rejected(tmp_path):
    """A verdict that does not say what it examined is not a verdict."""
    storage, fake, cycle, validator = make_cycle(tmp_path)
    prefix = f"projects/{cycle.project_id}/cycles/{cycle.cycle_id}/"
    paths = audit_artifacts(fake, "3" * 40, cycle, "PASS", [])
    uncovered = json.loads(fake.files[("audit", "3" * 40, prefix + "audit_result.json")])
    uncovered.pop("coverage")
    fake.files[("audit", "3" * 40, prefix + "audit_result.json")] = json.dumps(
        uncovered, sort_keys=True
    )
    manifest = json.loads(fake.files[("audit", "3" * 40, prefix + "report_manifest.json")])
    manifest["files"]["audit_result.json"]["sha256"] = hashlib.sha256(
        fake.files[("audit", "3" * 40, prefix + "audit_result.json")].encode("utf-8")
    ).hexdigest()
    fake.files[("audit", "3" * 40, prefix + "report_manifest.json")] = json.dumps(
        manifest, sort_keys=True
    )
    fake.set_diff("audit", "0" * 40, "3" * 40, paths)

    result = validator.validate_audit_push(cycle.project_id, "0" * 40, "3" * 40)

    assert not result.valid
    assert any("coverage" in error for error in result.errors)


def test_receipt_without_prompt_hash_is_rejected(tmp_path):
    """The receipt must name the prompt that produced it."""
    storage, fake, cycle, validator = make_cycle(tmp_path)
    prefix = f"projects/{cycle.project_id}/cycles/{cycle.cycle_id}/"
    paths = audit_artifacts(fake, "3" * 40, cycle, "PASS", [])
    metadata = json.loads(fake.files[("audit", "3" * 40, prefix + "codex_run_metadata.json")])
    metadata.pop("prompt_sha256")
    fake.files[("audit", "3" * 40, prefix + "codex_run_metadata.json")] = json.dumps(
        metadata, sort_keys=True
    )
    manifest = json.loads(fake.files[("audit", "3" * 40, prefix + "report_manifest.json")])
    manifest["files"]["codex_run_metadata.json"]["sha256"] = hashlib.sha256(
        fake.files[("audit", "3" * 40, prefix + "codex_run_metadata.json")].encode("utf-8")
    ).hexdigest()
    fake.files[("audit", "3" * 40, prefix + "report_manifest.json")] = json.dumps(
        manifest, sort_keys=True
    )
    fake.set_diff("audit", "0" * 40, "3" * 40, paths)

    result = validator.validate_audit_push(cycle.project_id, "0" * 40, "3" * 40)

    assert not result.valid
    assert any("prompt_sha256" in error for error in result.errors)


def test_a_low_finding_in_a_block_cycle_need_not_declare_blocked_scopes(tmp_path):
    """Constitution 12: only CRITICAL and HIGH gate an increment.

    Requiring blocked_scopes on every finding of a BLOCK cycle forced a LOW
    finding to declare what it blocks, and rejected an auditor that graded
    honestly — which is what happened to a real cycle.
    """
    storage, fake, cycle, validator = make_cycle(tmp_path)
    result = validate_artifacts(
        fake, validator, cycle, "0" * 40, "3" * 40, decision="BLOCK",
        findings=[
            {"finding_id": "F-001", "title": "gating", "severity": "HIGH",
             "status": "OPEN", "blocked_scopes": ["publish_claim"]},
            {"finding_id": "F-002", "title": "recorded only", "severity": "LOW",
             "status": "OPEN"},
        ],
    )

    assert result.valid, result.errors
    assert storage.get_cycle(cycle.cycle_id).status.value == "FINAL"


def test_a_block_cycle_needs_something_that_actually_gates(tmp_path):
    storage, fake, cycle, validator = make_cycle(tmp_path)
    result = validate_artifacts(
        fake, validator, cycle, "0" * 40, "3" * 40, decision="BLOCK",
        findings=[{"finding_id": "F-001", "title": "advisory", "severity": "LOW",
                   "status": "OPEN"}],
    )

    assert not result.valid
    assert any("CRITICAL or HIGH" in e for e in result.errors)
