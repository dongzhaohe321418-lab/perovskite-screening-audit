from __future__ import annotations

import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from app.main import create_app
from app.storage import JsonStorage

from tests.utils import FakeGitHub, audit_artifacts, valid_audit_request


CONFIG = {
    "projects": [
        {
            "project_id": "perovskite-screening",
            "science_repo": "perovskite-screening",
            "science_branch": "main",
            "audit_repo": "perovskite-screening-audit",
            "audit_branch": "audit",
        }
    ]
}
SECRET = "test-webhook-secret"
SCIENCE_BEFORE = "a" * 40
SCIENCE_SHA = "b" * 40


def make_client(tmp_path, fake_github):
    storage = JsonStorage(tmp_path / "state.json")
    app = create_app(storage=storage, github=fake_github, project_config=CONFIG)
    return TestClient(app), storage


def science_payload(changed=None, after=SCIENCE_SHA):
    changed = changed or [".audit/audit_request.json"]
    return {
        "ref": "refs/heads/main",
        "before": SCIENCE_BEFORE,
        "after": after,
        "repository": {"name": "perovskite-screening"},
        "commits": [{"added": [], "modified": changed, "removed": []}],
    }


def audit_payload(before, after, payload_paths):
    return {
        "ref": "refs/heads/audit",
        "before": before,
        "after": after,
        "repository": {"name": "perovskite-screening-audit"},
        "commits": [{"added": payload_paths, "modified": [], "removed": []}],
    }


def post_webhook(client, payload, delivery="delivery-1", *, sign=True):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {
        "X-GitHub-Event": "push",
        "X-GitHub-Delivery": delivery,
    }
    if sign:
        digest = hmac.new(SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
        headers["X-Hub-Signature-256"] = f"sha256={digest}"
    return client.post("/webhooks/github", content=body, headers=headers)


def configure_science_push(fake, changed=None):
    paths = changed or [".audit/audit_request.json"]
    fake.set_diff("science", SCIENCE_BEFORE, SCIENCE_SHA, paths)


def test_valid_science_webhook_creates_one_cycle(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    fake = FakeGitHub()
    configure_science_push(fake)
    fake.files[("science", SCIENCE_SHA, ".audit/audit_request.json")] = json.dumps(
        valid_audit_request()
    )
    client, storage = make_client(tmp_path, fake)

    response = post_webhook(client, science_payload())

    assert response.status_code == 200
    assert response.json()["cycle_status"] == "CODEX_TASK_CREATED"
    cycles = storage.list_cycles("perovskite-screening")
    assert len(cycles) == 1
    assert cycles[0].science_commit == SCIENCE_SHA


def test_webhook_fails_closed_without_secret(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    client, storage = make_client(tmp_path, FakeGitHub())

    response = post_webhook(client, science_payload())

    assert response.status_code == 503
    assert storage.list_cycles() == []


def test_webhook_rejects_unsigned_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    client, storage = make_client(tmp_path, FakeGitHub())

    response = post_webhook(client, science_payload(), sign=False)

    assert response.status_code == 401
    assert storage.list_cycles() == []


def test_duplicate_webhook_does_not_create_another_cycle(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    fake = FakeGitHub()
    configure_science_push(fake)
    fake.files[("science", SCIENCE_SHA, ".audit/audit_request.json")] = json.dumps(
        valid_audit_request()
    )
    client, storage = make_client(tmp_path, fake)

    first = post_webhook(client, science_payload(), delivery="same-delivery")
    second = post_webhook(client, science_payload(), delivery="same-delivery")

    assert first.status_code == 200
    assert second.json() == {"status": "duplicate_ignored"}
    assert len(storage.list_cycles()) == 1


def test_irrelevant_actual_diff_is_ignored_even_if_payload_claims_relevant(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    fake = FakeGitHub()
    configure_science_push(fake, ["docs/changelog.md"])
    client, storage = make_client(tmp_path, fake)

    response = post_webhook(
        client,
        science_payload(changed=[".audit/audit_request.json"]),
    )

    assert response.status_code == 200
    assert response.json()["reason"] == "irrelevant_science_change"
    assert storage.list_cycles() == []


def test_invalid_audit_request_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    fake = FakeGitHub()
    configure_science_push(fake)
    fake.files[("science", SCIENCE_SHA, ".audit/audit_request.json")] = json.dumps(
        {"project_id": "perovskite-screening"}
    )
    client, storage = make_client(tmp_path, fake)

    response = post_webhook(client, science_payload())

    assert response.status_code == 200
    assert response.json()["cycle_status"] == "AUDIT_REQUEST_INVALID"
    assert storage.list_cycles()[0].status.value == "AUDIT_REQUEST_INVALID"


def test_failed_delivery_can_be_retried(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    fake = FakeGitHub()
    configure_science_push(fake)
    fake.files[("science", SCIENCE_SHA, ".audit/audit_request.json")] = json.dumps(
        valid_audit_request()
    )
    fake.list_failures_remaining = 1
    client, storage = make_client(tmp_path, fake)

    first = post_webhook(client, science_payload(), delivery="retry-delivery")
    second = post_webhook(client, science_payload(), delivery="retry-delivery")

    assert first.status_code == 503
    assert second.status_code == 200
    assert len(storage.list_cycles()) == 1
    delivery = storage.delivery("retry-delivery")
    assert delivery["status"] == "COMPLETED"
    assert delivery["attempts"] == 2


def test_temporary_audit_request_read_failure_is_retried(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    fake = FakeGitHub()
    configure_science_push(fake)
    fake.files[("science", SCIENCE_SHA, ".audit/audit_request.json")] = json.dumps(
        valid_audit_request()
    )
    fake.file_failures_remaining = 1
    client, storage = make_client(tmp_path, fake)

    first = post_webhook(client, science_payload(), delivery="content-retry")
    second = post_webhook(client, science_payload(), delivery="content-retry")

    assert first.status_code == 503
    assert second.status_code == 200
    assert storage.list_cycles()[0].status.value == "CODEX_TASK_CREATED"


def test_audit_validation_uses_actual_diff_not_payload_file_list(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    fake = FakeGitHub()
    configure_science_push(fake)
    fake.files[("science", SCIENCE_SHA, ".audit/audit_request.json")] = json.dumps(
        valid_audit_request()
    )
    client, storage = make_client(tmp_path, fake)
    science_response = post_webhook(client, science_payload(), delivery="science-delivery")
    cycle = storage.get_cycle(science_response.json()["cycle_id"])

    before, after = "0" * 40, "c" * 40
    actual_paths = audit_artifacts(fake, after, cycle, decision="PASS", findings=[])
    actual_paths.append("projects/perovskite-screening/pi_approval.json")
    fake.set_diff("audit", before, after, actual_paths)
    payload_path = f"projects/perovskite-screening/cycles/{cycle.cycle_id}/audit_result.json"

    response = post_webhook(
        client,
        audit_payload(before, after, [payload_path]),
        delivery="audit-delivery",
    )

    assert response.status_code == 200
    assert response.json()["status"] == "audit_invalid"
    assert any("forbidden path" in error for error in response.json()["errors"])
    assert storage.get_cycle(cycle.cycle_id).status.value != "FINAL"
