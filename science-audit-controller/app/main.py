from __future__ import annotations

import hmac
import os
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, Header, HTTPException

from app.claude_adapter import ClaudeAdapter
from app.codex_adapter import CodexAdapter
from app.cycle_manager import CycleManager
from app.github_client import GitHubClient
from app.models import ActionAuthorization, ActionCheckRequest
from app.policy_engine import HIGH_RISK_ACTIONS, PolicyEngine
from app.report_validator import ClaudeDispositionValidator, ReportValidator
from app.storage import JsonStorage
from app.webhook import build_router


ROOT = Path(__file__).resolve().parents[1]


def load_project_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path or os.getenv("PROJECT_CONFIG_PATH", ROOT / "config/projects.example.yaml"))
    with config_path.open("r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh)
    if not isinstance(config, dict) or not isinstance(config.get("projects"), list):
        raise RuntimeError("project config must contain a projects list")
    return config


def create_app(
    storage: JsonStorage | None = None,
    github: GitHubClient | None = None,
    project_config: dict[str, Any] | None = None,
) -> FastAPI:
    project_config = project_config or load_project_config()
    projects = project_config.get("projects") or []
    if len(projects) != 1:
        raise RuntimeError("version 1.0 supports exactly one configured project per controller")
    storage = storage or JsonStorage()
    if github is None:
        first_project = projects[0]
        github = GitHubClient(
            science_repo=first_project.get("science_repo_full_name"),
            audit_repo=first_project.get("audit_repo_full_name"),
        )
    codex = CodexAdapter(storage, ROOT / "prompts")
    claude = ClaudeAdapter(storage, ROOT / "prompts")
    cycle_manager = CycleManager(storage, github, codex, ROOT / "schemas")
    initial_audit_heads = {
        project["project_id"]: project.get("audit_initial_commit", "0" * 40)
        for project in project_config.get("projects", [])
    }
    report_validator = ReportValidator(
        storage,
        github,
        claude,
        ROOT / "schemas",
        initial_audit_heads,
    )
    disposition_validator = ClaudeDispositionValidator(storage, github, ROOT / "schemas")
    policy = PolicyEngine(storage, {project["project_id"] for project in projects})

    app = FastAPI(title="science-audit-controller", version="1.0.0")
    app.state.storage = storage
    app.state.github = github
    app.state.project_config = project_config
    app.include_router(build_router(storage, github, cycle_manager, report_validator, project_config))

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/actions/check")
    def check_action(
        request: ActionCheckRequest,
        authorization: str | None = Header(default=None),
    ):
        _require_bearer_token("ACTION_API_TOKEN", authorization)
        return policy.check(request)

    @app.post("/claude/dispositions")
    def submit_claude_disposition(
        disposition: dict[str, Any],
        authorization: str | None = Header(default=None),
    ):
        _require_bearer_token("CLAUDE_API_TOKEN", authorization)
        return disposition_validator.validate(disposition)

    @app.post("/authorizations")
    def add_action_authorization(
        action_authorization: ActionAuthorization,
        authorization: str | None = Header(default=None),
    ):
        _require_bearer_token("PI_APPROVAL_TOKEN", authorization)
        if action_authorization.action not in HIGH_RISK_ACTIONS:
            raise HTTPException(status_code=400, detail="authorization is only valid for high-risk actions")
        storage.add_authorization(action_authorization)
        return {
            "status": "authorization_recorded",
            "authorization_id": action_authorization.authorization_id,
        }

    @app.get("/cycles")
    def list_cycles(
        project_id: str | None = None,
        authorization: str | None = Header(default=None),
    ):
        _require_bearer_token("CONTROLLER_READ_TOKEN", authorization)
        return storage.list_cycles(project_id)

    return app


def _require_bearer_token(environment_name: str, authorization: str | None) -> None:
    expected = os.getenv(environment_name)
    if not expected:
        raise HTTPException(status_code=503, detail=f"{environment_name} is not configured")
    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not supplied or not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=401, detail="invalid bearer token")


app = create_app()
