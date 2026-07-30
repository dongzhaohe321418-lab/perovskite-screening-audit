from __future__ import annotations

import json
import os
import re
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from app.cycle_manager import CycleManager
from app.github_client import GitHubClient
from app.json_utils import DuplicateJsonKeyError, strict_json_loads
from app.report_validator import ReportValidator
from app.storage import JsonStorage


DEFAULT_RELEVANT_PREFIXES = (
    ".audit/audit_request.json",
    "data/",
    "results/",
    "reports/",
    "scripts/",
    "src/",
)
FULL_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def build_router(
    storage: JsonStorage,
    github: GitHubClient,
    cycle_manager: CycleManager,
    report_validator: ReportValidator,
    project_config: dict[str, Any],
) -> APIRouter:
    router = APIRouter()

    @router.post("/webhooks/github")
    async def github_webhook(
        request: Request,
        x_github_event: str = Header(default=""),
        x_github_delivery: str = Header(default=""),
        x_hub_signature_256: str | None = Header(default=None),
    ):
        raw_body = await request.body()
        secret = os.getenv("GITHUB_WEBHOOK_SECRET")
        if not secret:
            raise HTTPException(status_code=503, detail="GitHub webhook secret is not configured")
        if not GitHubClient.verify_signature(secret, raw_body, x_hub_signature_256):
            raise HTTPException(status_code=401, detail="invalid GitHub signature")
        if not x_github_delivery:
            raise HTTPException(status_code=400, detail="missing GitHub delivery ID")

        claim = storage.claim_delivery(x_github_delivery)
        if claim == "COMPLETED":
            return {"status": "duplicate_ignored"}
        if claim == "PROCESSING":
            return {"status": "delivery_in_progress"}

        try:
            payload = strict_json_loads(raw_body or b"{}")
            if not isinstance(payload, dict):
                raise HTTPException(status_code=400, detail="webhook payload must be a JSON object")
            response = _process_push(
                x_github_event,
                payload,
                github,
                cycle_manager,
                report_validator,
                project_config,
            )
            storage.complete_delivery(x_github_delivery, response)
            return response
        except (json.JSONDecodeError, DuplicateJsonKeyError) as exc:
            storage.fail_delivery(x_github_delivery, str(exc))
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except HTTPException as exc:
            storage.fail_delivery(x_github_delivery, str(exc.detail))
            raise
        except Exception as exc:
            storage.fail_delivery(x_github_delivery, f"{type(exc).__name__}: {exc}")
            raise HTTPException(status_code=503, detail="webhook delivery processing failed") from exc

    return router


def _process_push(
    event_name: str,
    payload: dict[str, Any],
    github: GitHubClient,
    cycle_manager: CycleManager,
    report_validator: ReportValidator,
    project_config: dict[str, Any],
) -> dict[str, Any]:
    if event_name != "push":
        return {"status": "ignored", "reason": "unsupported_event"}

    repo_identifier = _repo_identifier(payload)
    project, repo_kind = _project_for_repo(project_config, repo_identifier)
    if not project or not repo_kind:
        return {"status": "ignored", "reason": "unknown_repository"}
    if payload.get("deleted") is True:
        return {"status": "ignored", "reason": "deleted_ref"}

    ref = payload.get("ref")
    after_sha = payload.get("after")
    before_sha = payload.get("before")
    if not isinstance(after_sha, str) or not FULL_SHA_RE.fullmatch(after_sha):
        raise HTTPException(status_code=400, detail="push is missing a full after commit SHA")
    if not isinstance(before_sha, str) or not FULL_SHA_RE.fullmatch(before_sha):
        raise HTTPException(status_code=400, detail="push has an invalid before commit SHA")

    if repo_kind == "science":
        if ref != f"refs/heads/{project.get('science_branch', 'main')}":
            return {"status": "ignored", "reason": "non_science_branch"}
        changed_files = github.list_changed_files("science", before_sha, after_sha)
        if not _has_relevant_science_change(changed_files, project):
            return {"status": "ignored", "reason": "irrelevant_science_change"}
        cycle = cycle_manager.handle_science_push(
            project["project_id"],
            project["science_repo"],
            after_sha,
        )
        return {
            "status": "cycle_processed",
            "cycle_id": cycle.cycle_id,
            "cycle_status": cycle.status.value,
        }

    if ref != f"refs/heads/{project.get('audit_branch', 'audit')}":
        return {"status": "ignored", "reason": "non_audit_branch"}
    result = report_validator.validate_audit_push(
        project["project_id"],
        before_sha,
        after_sha,
    )
    return {
        "status": "audit_validated" if result.valid else "audit_invalid",
        "errors": result.errors,
    }


def _repo_identifier(payload: dict[str, Any]) -> str:
    repo = payload.get("repository") or {}
    return repo.get("full_name") or repo.get("name") or ""


def _project_for_repo(
    config: dict[str, Any],
    repo_identifier: str,
) -> tuple[dict[str, Any] | None, str | None]:
    short_name = repo_identifier.split("/")[-1]
    for project in config.get("projects", []):
        science_names = {
            project.get("science_repo"),
            project.get("science_repo_full_name"),
        }
        audit_names = {
            project.get("audit_repo"),
            project.get("audit_repo_full_name"),
        }
        if repo_identifier in science_names or (
            "/" not in repo_identifier and short_name == project.get("science_repo")
        ):
            return project, "science"
        if repo_identifier in audit_names or (
            "/" not in repo_identifier and short_name == project.get("audit_repo")
        ):
            return project, "audit"
    return None, None


def _has_relevant_science_change(changed_files: list[str], project: dict[str, Any]) -> bool:
    prefixes = tuple(project.get("science_relevant_paths") or DEFAULT_RELEVANT_PREFIXES)
    return any(path == ".audit/audit_request.json" or path.startswith(prefixes) for path in changed_files)
