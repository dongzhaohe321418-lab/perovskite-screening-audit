from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.blocker_reducer import reduce_blockers
from app.claude_adapter import ClaudeAdapter
from app.main import create_app
from app.models import BlockerEvent, blocker_event_sha256
from app.report_validator import ReportValidator
from app.storage import JsonStorage
from tests.test_report_validator import final_blocked_cycle, pending_cycle_at_commit
from tests.test_webhook import CONFIG
from tests.utils import ROOT, FakeGitHub, audit_artifacts


PI_HEADERS = {"Authorization": "Bearer pi-secret"}
ACTION_HEADERS = {"Authorization": "Bearer action-secret"}
READ_HEADERS = {"Authorization": "Bearer read-secret"}


def check_payload(action="submit_production_job"):
    return {
        "project_id": "perovskite-screening",
        "actor": "claude_science",
        "action": action,
        "science_commit": "d" * 40,
        "manifest_sha256": "a" * 64,
    }


def quarantine_payload(event_sha256, reason="Replayed closure for a finding that was never opened."):
    return {
        "project_id": "perovskite-screening",
        "event_sha256": event_sha256,
        "reason": reason,
        "approved_by": "principal-investigator",
    }


def test_action_endpoint_requires_configured_bearer_token(tmp_path, monkeypatch):
    monkeypatch.delenv("ACTION_API_TOKEN", raising=False)
    app = create_app(
        storage=JsonStorage(tmp_path / "state.json"),
        github=FakeGitHub(),
        project_config=CONFIG,
    )
    client = TestClient(app)
    payload = {
        "project_id": "perovskite-screening",
        "actor": "claude_science",
        "action": "submit_production_job",
        "science_commit": "a" * 40,
        "manifest_sha256": "b" * 64,
    }

    missing_config = client.post("/actions/check", json=payload)
    monkeypatch.setenv("ACTION_API_TOKEN", "action-secret")
    wrong_token = client.post(
        "/actions/check",
        json=payload,
        headers={"Authorization": "Bearer wrong"},
    )
    accepted = client.post(
        "/actions/check",
        json=payload,
        headers={"Authorization": "Bearer action-secret"},
    )

    assert missing_config.status_code == 503
    assert wrong_token.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json()["decision"] == "DENY"


def test_claude_disposition_endpoint_rejects_unauthenticated_writes(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_API_TOKEN", "claude-secret")
    app = create_app(
        storage=JsonStorage(tmp_path / "state.json"),
        github=FakeGitHub(),
        project_config=CONFIG,
    )
    client = TestClient(app)

    response = client.post("/claude/dispositions", json={})

    assert response.status_code == 401


def test_quarantine_endpoint_requires_the_pi_token(tmp_path, monkeypatch):
    monkeypatch.delenv("PI_APPROVAL_TOKEN", raising=False)
    storage, fake, _ = final_blocked_cycle(tmp_path)
    client = TestClient(create_app(storage=storage, github=fake, project_config=CONFIG))
    payload = quarantine_payload(blocker_event_sha256(storage.event_log()[0]))

    missing_config = client.post("/admin/quarantine-event", json=payload)
    monkeypatch.setenv("PI_APPROVAL_TOKEN", "pi-secret")
    missing_token = client.post("/admin/quarantine-event", json=payload)
    wrong_token = client.post(
        "/admin/quarantine-event",
        json=payload,
        headers={"Authorization": "Bearer wrong"},
    )
    accepted = client.post("/admin/quarantine-event", json=payload, headers=PI_HEADERS)

    assert missing_config.status_code == 503
    assert missing_token.status_code == 401
    assert wrong_token.status_code == 401
    assert accepted.status_code == 200
    assert len(storage.quarantines()) == 1


def test_double_quarantine_of_the_same_hash_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("PI_APPROVAL_TOKEN", "pi-secret")
    storage, fake, _ = final_blocked_cycle(tmp_path)
    client = TestClient(create_app(storage=storage, github=fake, project_config=CONFIG))
    payload = quarantine_payload(blocker_event_sha256(storage.event_log()[0]))

    first = client.post("/admin/quarantine-event", json=payload, headers=PI_HEADERS)
    second = client.post("/admin/quarantine-event", json=payload, headers=PI_HEADERS)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    assert len(storage.quarantines("perovskite-screening")) == 1


def test_quarantine_of_an_unmatched_hash_is_recorded_without_effect(tmp_path, monkeypatch):
    monkeypatch.setenv("PI_APPROVAL_TOKEN", "pi-secret")
    monkeypatch.setenv("CONTROLLER_READ_TOKEN", "read-secret")
    storage, fake, _ = final_blocked_cycle(tmp_path)
    client = TestClient(create_app(storage=storage, github=fake, project_config=CONFIG))
    unmatched = "f" * 64

    recorded = client.post(
        "/admin/quarantine-event",
        json=quarantine_payload(unmatched, reason="Quarantined ahead of a replay."),
        headers=PI_HEADERS,
    )
    events = client.get(
        "/events",
        params={"project_id": "perovskite-screening"},
        headers=READ_HEADERS,
    )

    state = reduce_blockers(
        storage.event_log(),
        "perovskite-screening",
        quarantined=storage.quarantined_event_hashes("perovskite-screening"),
    )
    assert recorded.json()["matched_event_indices"] == []
    assert [item["event_sha256"] for item in events.json()["quarantined_events"]] == [unmatched]
    assert not state.fail_closed
    assert set(state.active) == {"F-001", "F-002"}


def test_event_read_endpoint_requires_the_read_token_and_reports_canonical_hashes(
    tmp_path,
    monkeypatch,
):
    monkeypatch.delenv("CONTROLLER_READ_TOKEN", raising=False)
    storage, fake, _ = final_blocked_cycle(tmp_path)
    projectless = BlockerEvent(event="FINDING_OPENED", finding_id="F-ORPHAN")
    storage.append_event(projectless)
    client = TestClient(create_app(storage=storage, github=fake, project_config=CONFIG))

    missing_config = client.get("/events")
    monkeypatch.setenv("CONTROLLER_READ_TOKEN", "read-secret")
    missing_token = client.get("/events")
    authenticated = client.get("/events", headers=READ_HEADERS)
    scoped = client.get(
        "/events",
        params={"project_id": "perovskite-screening"},
        headers=READ_HEADERS,
    )

    events = storage.event_log()
    records = authenticated.json()["events"]
    assert missing_config.status_code == 503
    assert missing_token.status_code == 401
    assert [record["event_sha256"] for record in records] == [
        blocker_event_sha256(event) for event in events
    ]
    assert [record["index"] for record in records] == list(range(len(events)))
    assert authenticated.json()["quarantined_events"] == []
    assert scoped.json()["events"][-1] == {
        "index": len(events) - 1,
        "event_sha256": blocker_event_sha256(projectless),
        "event": projectless.model_dump(mode="json"),
    }


def test_poisoned_blocker_state_is_repaired_only_by_pi_quarantine(tmp_path, monkeypatch):
    monkeypatch.setenv("ACTION_API_TOKEN", "action-secret")
    monkeypatch.setenv("PI_APPROVAL_TOKEN", "pi-secret")
    storage, fake, first_cycle = final_blocked_cycle(tmp_path)
    poison = BlockerEvent(
        event="FINDING_VERIFIED_CLOSED",
        finding_id="F-404",
        project_id="perovskite-screening",
        cycle_id=first_cycle.cycle_id,
    )
    storage.append_event(poison)
    second_cycle = pending_cycle_at_commit(storage, fake, "8" * 40)
    report_validator = ReportValidator(
        storage,
        fake,
        ClaudeAdapter(storage, ROOT / "prompts"),
        ROOT / "schemas",
    )
    before, after = storage.audit_head("perovskite-screening"), "b" * 40
    fake.set_diff(
        "audit",
        before,
        after,
        audit_artifacts(fake, after, second_cycle, decision="PASS", findings=[]),
    )
    client = TestClient(create_app(storage=storage, github=fake, project_config=CONFIG))

    poisoned_check = client.post("/actions/check", json=check_payload(), headers=ACTION_HEADERS)
    poisoned_low_risk = client.post(
        "/actions/check",
        json=check_payload(action="run_unit_tests"),
        headers=ACTION_HEADERS,
    )
    poisoned_push = report_validator.validate_audit_push("perovskite-screening", before, after)

    quarantine = client.post(
        "/admin/quarantine-event",
        json=quarantine_payload(blocker_event_sha256(poison)),
        headers=PI_HEADERS,
    )
    repaired_low_risk = client.post(
        "/actions/check",
        json=check_payload(action="run_unit_tests"),
        headers=ACTION_HEADERS,
    )
    repaired_check = client.post("/actions/check", json=check_payload(), headers=ACTION_HEADERS)
    repaired_push = report_validator.validate_audit_push("perovskite-screening", before, after)

    assert poisoned_check.json()["reason_codes"] == ["BLOCKER_STATE_INCONSISTENT"]
    assert poisoned_low_risk.json()["reason_codes"] == ["BLOCKER_STATE_INCONSISTENT"]
    assert poisoned_push.errors == ["blocker event state is inconsistent"]
    assert quarantine.json()["matched_event_indices"] == [len(storage.event_log()) - 1]
    assert repaired_low_risk.json()["decision"] == "ALLOW"
    assert repaired_check.json()["decision"] == "DENY"
    assert "ACTIVE_BLOCKER_F-001" in repaired_check.json()["reason_codes"]
    assert "BLOCKER_STATE_INCONSISTENT" not in repaired_check.json()["reason_codes"]
    assert repaired_push.valid, repaired_push.errors
    assert storage.get_cycle(second_cycle.cycle_id).status.value == "FINAL"
    assert poison in storage.event_log()


def test_fail_closed_error_names_the_hash_the_quarantine_endpoint_accepts(tmp_path, monkeypatch):
    monkeypatch.setenv("PI_APPROVAL_TOKEN", "pi-secret")
    storage, fake, _ = final_blocked_cycle(tmp_path)
    storage.append_event(
        BlockerEvent(
            event="FINDING_RESOLVED_BY_FIAT",
            finding_id="F-001",
            project_id="perovskite-screening",
        )
    )
    client = TestClient(create_app(storage=storage, github=fake, project_config=CONFIG))
    poisoned = reduce_blockers(storage.event_log(), "perovskite-screening")
    named_hashes = re.findall(r"event_sha256=([0-9a-f]{64})", " ".join(poisoned.errors))

    responses = [
        client.post(
            "/admin/quarantine-event",
            json=quarantine_payload(event_sha256, reason="Unknown event type from a bad writer."),
            headers=PI_HEADERS,
        )
        for event_sha256 in named_hashes
    ]

    repaired = reduce_blockers(
        storage.event_log(),
        "perovskite-screening",
        quarantined=storage.quarantined_event_hashes("perovskite-screening"),
    )
    assert poisoned.fail_closed
    assert len(named_hashes) == 1
    assert [response.status_code for response in responses] == [200]
    assert responses[0].json()["matched_event_indices"] == [len(storage.event_log()) - 1]
    assert not repaired.fail_closed
    assert set(repaired.active) == {"F-001", "F-002"}
