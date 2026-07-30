from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import ActionAuthorization, ActionCheckRequest
from app.policy_engine import PolicyEngine

from tests.test_cycle_manager import make_cycle, validate_artifacts
from tests.test_report_validator import final_blocked_cycle


def action_request(*, commit="d" * 40, manifest="a" * 64, action="submit_production_job"):
    return ActionCheckRequest(
        project_id="perovskite-screening",
        actor="claude_science",
        action=action,
        science_commit=commit,
        manifest_sha256=manifest,
    )


def add_full_authorization(storage, *, commit="d" * 40, manifest="a" * 64):
    storage.add_authorization(
        ActionAuthorization(
            authorization_id="AUTH-001",
            project_id="perovskite-screening",
            actor="claude_science",
            action="submit_production_job",
            science_commit=commit,
            manifest_sha256=manifest,
            policy_approved=True,
            budget_approved=True,
            pi_approved=True,
            approved_by="principal-investigator",
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        )
    )


def test_active_blocker_denies_production_action(tmp_path):
    storage, _, _ = final_blocked_cycle(tmp_path)
    policy = PolicyEngine(storage)

    response = policy.check(action_request())

    assert response.decision == "DENY"
    assert "ACTIVE_BLOCKER_F-001" in response.reason_codes


def test_high_risk_action_is_denied_without_final_audit_and_approvals(tmp_path):
    storage, _, _, _ = make_cycle(tmp_path)
    policy = PolicyEngine(storage)

    response = policy.check(action_request())

    assert response.decision == "DENY"
    assert "NO_FINAL_AUDIT_FOR_COMMIT" in response.reason_codes
    assert "POLICY_APPROVAL_REQUIRED" in response.reason_codes
    assert "BUDGET_APPROVAL_REQUIRED" in response.reason_codes
    assert "PI_APPROVAL_REQUIRED" in response.reason_codes


def test_high_risk_action_allows_only_exact_final_audit_and_authorization(tmp_path):
    storage, fake, cycle, validator = make_cycle(tmp_path)
    assert validate_artifacts(
        fake,
        validator,
        cycle,
        "0" * 40,
        "2" * 40,
    ).valid
    add_full_authorization(storage)
    policy = PolicyEngine(storage)

    response = policy.check(action_request())

    assert response.decision == "ALLOW"
    assert response.reason_codes == []


def test_manifest_mismatch_denies_even_with_other_approvals(tmp_path):
    storage, fake, cycle, validator = make_cycle(tmp_path)
    assert validate_artifacts(
        fake,
        validator,
        cycle,
        "0" * 40,
        "2" * 40,
    ).valid
    add_full_authorization(storage, manifest="b" * 64)
    policy = PolicyEngine(storage)

    response = policy.check(action_request(manifest="b" * 64))

    assert response.decision == "DENY"
    assert "MANIFEST_MISMATCH" in response.reason_codes


def test_expired_authorization_is_denied(tmp_path):
    storage, fake, cycle, validator = make_cycle(tmp_path)
    assert validate_artifacts(
        fake,
        validator,
        cycle,
        "0" * 40,
        "2" * 40,
    ).valid
    storage.add_authorization(
        ActionAuthorization(
            authorization_id="AUTH-EXPIRED",
            project_id="perovskite-screening",
            actor="claude_science",
            action="submit_production_job",
            science_commit=cycle.science_commit,
            manifest_sha256=cycle.evidence_manifest_sha256,
            policy_approved=True,
            budget_approved=True,
            pi_approved=True,
            approved_by="principal-investigator",
            expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        )
    )

    response = PolicyEngine(storage).check(action_request())

    assert response.decision == "DENY"
    assert "PI_APPROVAL_REQUIRED" in response.reason_codes


def test_non_blocked_low_risk_action_can_pass_policy_check(tmp_path):
    storage, _, _ = final_blocked_cycle(tmp_path)
    policy = PolicyEngine(storage)

    response = policy.check(action_request(action="run_unit_tests"))

    assert response.decision == "ALLOW"
    assert response.reason_codes == []


def test_unknown_actor_is_denied(tmp_path):
    storage, _, _, _ = make_cycle(tmp_path)
    request = action_request()
    request.actor = "untrusted_actor"

    response = PolicyEngine(storage).check(request)

    assert response.decision == "DENY"
    assert response.reason_codes == ["ACTOR_NOT_ALLOWED"]


def test_unknown_project_is_denied(tmp_path):
    storage, _, _, _ = make_cycle(tmp_path)
    request = action_request(action="run_unit_tests")
    request.project_id = "unknown-project"

    response = PolicyEngine(storage, {"perovskite-screening"}).check(request)

    assert response.decision == "DENY"
    assert response.reason_codes == ["UNKNOWN_PROJECT"]


def test_unknown_action_is_denied_not_allowed(tmp_path):
    storage, _, _ = final_blocked_cycle(tmp_path)

    response = PolicyEngine(storage).check(action_request(action="submit_production_job_v2"))

    assert response.decision == "DENY"
    assert response.reason_codes == ["UNKNOWN_ACTION"]
