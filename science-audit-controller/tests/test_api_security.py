from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.storage import JsonStorage
from tests.test_webhook import CONFIG
from tests.utils import FakeGitHub


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
