from __future__ import annotations

import json

from app.blocker_reducer import reduce_blockers
from app.claude_adapter import ClaudeAdapter
from app.codex_adapter import CodexAdapter
from app.cycle_manager import CycleManager
from app.report_validator import ClaudeDispositionValidator, ReportValidator

from tests.test_cycle_manager import make_cycle, validate_artifacts
from tests.utils import ROOT, audit_artifacts, valid_audit_request


def final_blocked_cycle(tmp_path):
    storage, fake, cycle, validator = make_cycle(tmp_path)
    before, after = "0" * 40, "3" * 40
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
                "title": "Issue 1",
                "severity": "HIGH",
                "status": "OPEN",
                "blocked_scopes": ["production"],
            },
            {
                "finding_id": "F-002",
                "title": "Issue 2",
                "severity": "MEDIUM",
                "status": "OPEN",
                "blocked_scopes": ["publish_claim"],
            },
        ],
    )
    assert result.valid
    return storage, fake, storage.get_cycle(cycle.cycle_id)


def disposition_for(cycle, findings):
    return {
        "cycle_id": cycle.cycle_id,
        "audit_report_id": cycle.audit_report_id,
        "report_sha256_confirmed": True,
        "report_sha256": cycle.audit_report_sha256,
        "findings": findings,
    }


def test_claude_disposition_missing_a_finding_is_rejected(tmp_path):
    storage, fake, cycle = final_blocked_cycle(tmp_path)
    validator = ClaudeDispositionValidator(storage, fake, ROOT / "schemas")

    result = validator.validate(
        disposition_for(
            cycle,
            [{"finding_id": "F-001", "disposition": "ACCEPT_AND_STOP"}],
        )
    )

    assert not result.valid
    assert any("missing finding" in error for error in result.errors)


def test_claude_disposition_with_unknown_finding_is_rejected(tmp_path):
    storage, fake, cycle = final_blocked_cycle(tmp_path)
    validator = ClaudeDispositionValidator(storage, fake, ROOT / "schemas")

    result = validator.validate(
        disposition_for(
            cycle,
            [
                {"finding_id": "F-001", "disposition": "ACCEPT_AND_STOP"},
                {"finding_id": "F-002", "disposition": "PASS_NO_ACTION"},
                {"finding_id": "F-999", "disposition": "DISAGREE_WITH_EVIDENCE"},
            ],
        )
    )

    assert not result.valid
    assert any("unknown finding" in error for error in result.errors)


def test_duplicate_finding_dispositions_are_rejected(tmp_path):
    storage, fake, cycle = final_blocked_cycle(tmp_path)
    validator = ClaudeDispositionValidator(storage, fake, ROOT / "schemas")

    result = validator.validate(
        disposition_for(
            cycle,
            [
                {"finding_id": "F-001", "disposition": "ACCEPT_AND_STOP"},
                {"finding_id": "F-001", "disposition": "PASS_NO_ACTION"},
                {"finding_id": "F-002", "disposition": "PASS_NO_ACTION"},
            ],
        )
    )

    assert not result.valid
    assert "duplicate finding dispositions are not allowed" in result.errors


def test_disposition_must_confirm_exact_report_hash(tmp_path):
    storage, fake, cycle = final_blocked_cycle(tmp_path)
    validator = ClaudeDispositionValidator(storage, fake, ROOT / "schemas")
    payload = disposition_for(
        cycle,
        [
            {"finding_id": "F-001", "disposition": "ACCEPT_AND_STOP"},
            {"finding_id": "F-002", "disposition": "PASS_NO_ACTION"},
        ],
    )
    payload["report_sha256"] = "0" * 64

    result = validator.validate(payload)

    assert not result.valid
    assert any("does not match" in error for error in result.errors)


def test_duplicate_cycle_disposition_is_rejected(tmp_path):
    storage, fake, cycle = final_blocked_cycle(tmp_path)
    validator = ClaudeDispositionValidator(storage, fake, ROOT / "schemas")
    payload = disposition_for(
        cycle,
        [
            {"finding_id": "F-001", "disposition": "ACCEPT_AND_STOP"},
            {"finding_id": "F-002", "disposition": "PASS_NO_ACTION"},
        ],
    )

    assert validator.validate(payload).valid
    duplicate = validator.validate(payload)

    assert not duplicate.valid
    assert duplicate.errors == ["disposition already recorded for cycle"]


def test_finding_closes_only_after_later_audit_verifies_submitted_fix(tmp_path):
    storage, fake, first_cycle = final_blocked_cycle(tmp_path)
    disposition_validator = ClaudeDispositionValidator(storage, fake, ROOT / "schemas")
    fix_commit = "4" * 40
    fake.existing_commits.add(fix_commit)
    disposition = disposition_for(
        first_cycle,
        [
            {
                "finding_id": "F-001",
                "disposition": "ACCEPT_AND_FIX",
                "fix_commit": fix_commit,
            },
            {"finding_id": "F-002", "disposition": "ACCEPT_AND_STOP"},
        ],
    )
    assert disposition_validator.validate(disposition).valid
    assert "F-001" in reduce_blockers(storage.event_log(), first_cycle.project_id).active

    fake.files[("science", fix_commit, ".audit/audit_request.json")] = json.dumps(
        valid_audit_request()
    )
    manager = CycleManager(
        storage,
        fake,
        CodexAdapter(storage, ROOT / "prompts"),
        ROOT / "schemas",
    )
    second_cycle = manager.handle_science_push(
        "perovskite-screening",
        "perovskite-screening",
        fix_commit,
    )
    report_validator = ReportValidator(
        storage,
        fake,
        ClaudeAdapter(storage, ROOT / "prompts"),
        ROOT / "schemas",
    )
    before, after = storage.audit_head(first_cycle.project_id), "6" * 40
    paths = audit_artifacts(
        fake,
        after,
        second_cycle,
        decision="PASS",
        findings=[],
        verified_closed_findings=[
            {
                "finding_id": "F-001",
                "verification_summary": "Regression test passes at the submitted fix commit.",
            }
        ],
    )
    fake.set_diff("audit", before, after, paths)

    result = report_validator.validate_audit_push(
        "perovskite-screening",
        before,
        after,
    )

    state = reduce_blockers(storage.event_log(), first_cycle.project_id)
    assert result.valid
    assert "F-001" not in state.active
    assert "F-001" not in state.findings
    assert "F-002" in state.active


def test_audit_cannot_close_finding_without_matching_fix_commit(tmp_path):
    storage, fake, first_cycle = final_blocked_cycle(tmp_path)
    other_commit = "7" * 40
    fake.files[("science", other_commit, ".audit/audit_request.json")] = json.dumps(
        valid_audit_request()
    )
    manager = CycleManager(
        storage,
        fake,
        CodexAdapter(storage, ROOT / "prompts"),
        ROOT / "schemas",
    )
    second_cycle = manager.handle_science_push(
        "perovskite-screening",
        "perovskite-screening",
        other_commit,
    )
    validator = ReportValidator(
        storage,
        fake,
        ClaudeAdapter(storage, ROOT / "prompts"),
        ROOT / "schemas",
    )
    before, after = storage.audit_head(first_cycle.project_id), "9" * 40
    paths = audit_artifacts(
        fake,
        after,
        second_cycle,
        decision="PASS",
        findings=[],
        verified_closed_findings=[
            {"finding_id": "F-001", "verification_summary": "Claimed closed."}
        ],
    )
    fake.set_diff("audit", before, after, paths)

    result = validator.validate_audit_push("perovskite-screening", before, after)

    assert not result.valid
    assert any("matching submitted fix" in error for error in result.errors)
    assert "F-001" in reduce_blockers(storage.event_log(), first_cycle.project_id).active


def test_fix_commit_must_descend_from_audited_commit(tmp_path):
    storage, fake, cycle = final_blocked_cycle(tmp_path)
    validator = ClaudeDispositionValidator(storage, fake, ROOT / "schemas")
    fix_commit = "5" * 40
    fake.existing_commits.add(fix_commit)
    fake.ancestor_results[("science", cycle.science_commit, fix_commit)] = False

    result = validator.validate(
        disposition_for(
            cycle,
            [
                {"finding_id": "F-001", "disposition": "ACCEPT_AND_FIX", "fix_commit": fix_commit},
                {"finding_id": "F-002", "disposition": "PASS_NO_ACTION"},
            ],
        )
    )

    assert not result.valid
    assert any("does not descend" in error for error in result.errors)


def test_fix_commit_marks_existing_open_cycle_as_the_reaudit(tmp_path):
    """The push that creates a fix commit opens its cycle before the disposition
    naming it arrives, so the disposition must retro-mark that cycle."""
    storage, fake, first_cycle = final_blocked_cycle(tmp_path)
    fix_commit = "6" * 40
    fake.existing_commits.add(fix_commit)
    fake.files[("science", fix_commit, ".audit/audit_request.json")] = json.dumps(
        valid_audit_request()
    )
    codex = CodexAdapter(storage, ROOT / "prompts")
    manager = CycleManager(storage, fake, codex, ROOT / "schemas")
    second_cycle = manager.handle_science_push(
        first_cycle.project_id, first_cycle.science_repo, fix_commit
    )
    assert reduce_blockers(storage.event_log(), first_cycle.project_id).reaudit_cycles == {}

    validator = ClaudeDispositionValidator(storage, fake, ROOT / "schemas")
    result = validator.validate(
        disposition_for(
            first_cycle,
            [
                {"finding_id": "F-001", "disposition": "ACCEPT_AND_FIX", "fix_commit": fix_commit},
                {"finding_id": "F-002", "disposition": "PASS_NO_ACTION"},
            ],
        )
    )

    assert result.valid, result.errors
    state = reduce_blockers(storage.event_log(), first_cycle.project_id)
    assert state.reaudit_cycles["F-001"] == second_cycle.cycle_id
    assert not state.fail_closed
